from __future__ import annotations

import datetime as dt
import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import config

try:
    import mss
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    mss = None
    Image = None  # type: ignore[assignment,misc]

try:  # pragma: no cover - optional dependency
    import win32gui
except ModuleNotFoundError:
    win32gui = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ScreenshotStatus:
    is_running: bool
    screenshot_count: int
    last_screenshot_path: Optional[Path]
    meeting_title: str


@dataclass(frozen=True)
class SavedScreenshotInfo:
    path: Path
    exact_hash: str
    perceptual_hash: int


class ScreenshotCapture:
    def __init__(
        self,
        output_dir: Path = config.SCREENSHOT_DIR,
        check_interval: float = config.SCREENSHOT_CHECK_INTERVAL,
        change_threshold: float = config.SCREENSHOT_CHANGE_THRESHOLD,
        hash_size: int = config.SCREENSHOT_HASH_SIZE,
        stability_samples: int = config.SCREENSHOT_STABILITY_SAMPLES,
        stability_interval: float = config.SCREENSHOT_STABILITY_INTERVAL,
    ) -> None:
        self._output_dir = output_dir
        self._check_interval = check_interval
        self._change_threshold = change_threshold
        self._hash_size = hash_size
        self._stability_samples = stability_samples
        self._stability_interval = stability_interval

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

        self._meeting_title_display = "未検出"
        self._meeting_title_slug = config.DEFAULT_MEETING_SLUG
        self._screenshot_count = 0
        self._last_screenshot_path: Optional[Path] = None
        self._last_hash: Optional[str] = None
        self._saved_screenshots: dict[str, SavedScreenshotInfo] = {}
        self._pending_hash: Optional[str] = None
        self._pending_perceptual_hash: Optional[int] = None
        self._pending_count = 0

        self._status_lock = threading.Lock()
        self._status_callback: Optional[Callable[[ScreenshotStatus], None]] = None

    @property
    def is_available(self) -> bool:
        return mss is not None and Image is not None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def screenshot_count(self) -> int:
        with self._status_lock:
            return self._screenshot_count

    @property
    def last_screenshot_path(self) -> Optional[Path]:
        with self._status_lock:
            return self._last_screenshot_path

    @property
    def status(self) -> ScreenshotStatus:
        with self._status_lock:
            return ScreenshotStatus(
                is_running=self._running,
                screenshot_count=self._screenshot_count,
                last_screenshot_path=self._last_screenshot_path,
                meeting_title=self._meeting_title_display,
            )

    def register_status_callback(self, callback: Callable[[ScreenshotStatus], None]) -> None:
        self._status_callback = callback

    def start(self, meeting_title: str, meeting_title_slug: str) -> None:
        if not self.is_available:
            logging.warning("mss / Pillow がインストールされていないため、スクリーンショット取得をスキップします。")
            return
        if self.is_running:
            logging.debug("ScreenshotCapture is already running.")
            return

        self._meeting_title_display = meeting_title
        self._meeting_title_slug = meeting_title_slug
        self._screenshot_count = 0
        self._last_screenshot_path = None
        self._last_hash = None
        self._saved_screenshots.clear()
        self._pending_hash = None
        self._pending_perceptual_hash = None

        target_dir = self._prepare_output_directory()
        if not target_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)
        
        # Load existing hashes from saved screenshots to avoid duplicates
        self._load_existing_hashes(target_dir)

        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, name="ScreenshotCapture", daemon=True)
        self._thread.start()
        logging.info("スクリーンショット取得を開始しました。")
        self._emit_status()

    def stop(self) -> None:
        if not self.is_running:
            return

        self._stop_event.set()
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

        logging.info("スクリーンショット取得を終了しました。合計枚数: %d", self._screenshot_count)
        self._emit_status()

    def close(self) -> None:
        self.stop()

    def _prepare_output_directory(self) -> Path:
        today = dt.datetime.now().strftime("%Y%m%d")
        return self._output_dir / today / self._meeting_title_slug

    def _capture_loop(self) -> None:
        assert mss is not None and Image is not None

        with mss.mss() as sct:
            while not self._stop_event.is_set():
                start_time = time.perf_counter()
                try:
                    # Try to capture screen share window first
                    captured = self._try_capture_screen_share(sct)
                    
                    # If no screen share window, fall back to full screen
                    if not captured:
                        monitor = sct.monitors[1]  # Primary monitor
                        self._capture_and_check_stability(sct, monitor)
                        
                except Exception:
                    logging.exception("スクリーンショット取得中にエラーが発生しました。")

                elapsed = time.perf_counter() - start_time
                sleep_time = max(0.0, self._stability_interval - elapsed)
                if self._stop_event.wait(timeout=sleep_time):
                    break

    def _try_capture_screen_share(self, sct) -> bool:
        """
        Try to capture only the screen share window.
        Returns True if screen share window was captured, False otherwise.
        """
        if win32gui is None:
            return False
        
        from . import process_utils
        
        share_window = process_utils.get_zoom_screen_share_window()
        if not share_window:
            return False
        
        hwnd, title = share_window
        
        try:
            # Get window rectangle
            rect = win32gui.GetWindowRect(hwnd)
            left, top, right, bottom = rect
            width = right - left
            height = bottom - top
            
            # Skip if window is too small (probably not actual content)
            if width < 200 or height < 200:
                return False
            
            # Create monitor dict for this window
            monitor = {
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            }
            
            # Capture this specific window area
            self._capture_and_check_stability(sct, monitor)
            return True
            
        except Exception:
            logging.debug("画面共有ウィンドウのキャプチャに失敗しました。")
            return False

    def _capture_and_check_stability(self, sct, monitor: dict) -> None:
        """Capture and wait for screen stability before saving."""
        assert Image is not None

        raw = sct.grab(monitor)
        image = Image.frombytes("RGB", raw.size, raw.rgb)

        # Compute hashes for duplicate/similarity detection
        current_hash = self._compute_exact_hash(image)
        perceptual_hash = self._compute_perceptual_hash(image)

        # Already saved check
        if current_hash in self._saved_screenshots:
            # Reset pending counter since we've seen this before
            self._reset_pending(current_hash)
            return

        similar_infos = self._find_similar_screenshots(perceptual_hash)
        if similar_infos:
            self._remove_saved_screenshots(similar_infos)

        # Stability check: require N consecutive identical hashes
        if self._pending_hash is None:
            self._pending_hash = current_hash
            self._pending_perceptual_hash = perceptual_hash
            self._pending_count = 1
        else:
            stable = False
            if self._pending_hash == current_hash:
                stable = True
            elif (
                self._pending_perceptual_hash is not None
                and self._are_hashes_similar(self._pending_perceptual_hash, perceptual_hash)
            ):
                stable = True

            if stable:
                self._pending_count += 1
            else:
                self._pending_hash = current_hash
                self._pending_perceptual_hash = perceptual_hash
                self._pending_count = 1

        if self._pending_count >= self._stability_samples:
            self._save_screenshot(image, current_hash, perceptual_hash)
            self._pending_hash = None
            self._pending_perceptual_hash = None
            self._pending_count = 0

    def _save_screenshot(self, image, current_hash: str, perceptual_hash: int) -> None:
        """Save a stable screenshot."""
        timestamp = dt.datetime.now()
        filename = f"screenshot_{timestamp.strftime('%H%M%S_%f')}.png"
        target_dir = self._prepare_output_directory()
        screenshot_path = target_dir / filename

        self._prepare_for_new_screenshot(current_hash, perceptual_hash)
        image.save(screenshot_path)

        with self._status_lock:
            self._screenshot_count += 1
            self._last_screenshot_path = screenshot_path

        self._last_hash = current_hash
        self._saved_screenshots[current_hash] = SavedScreenshotInfo(
            path=screenshot_path,
            exact_hash=current_hash,
            perceptual_hash=perceptual_hash,
        )
        logging.debug("新しい安定画面を保存しました: %s", screenshot_path)
        self._emit_status()

    def _compute_exact_hash(self, image) -> str:
        """Compute a cryptographic hash of the image for exact duplicate detection."""
        assert Image is not None
        rgb_image = image.convert("RGB")
        hasher = hashlib.sha256()
        width, height = rgb_image.size
        hasher.update(width.to_bytes(4, "big"))
        hasher.update(height.to_bytes(4, "big"))
        hasher.update(rgb_image.tobytes())
        return hasher.hexdigest()

    def _compute_perceptual_hash(self, image) -> int:
        """Compute a perceptual hash (average hash) for similarity detection."""
        assert Image is not None
        size = max(4, self._hash_size)
        grayscale = image.convert("L").resize((size, size), Image.Resampling.LANCZOS)
        pixels = list(grayscale.getdata())
        avg = sum(pixels) / len(pixels)
        bits = 0
        for pixel in pixels:
            bits = (bits << 1) | (1 if pixel >= avg else 0)
        return bits

    def _find_similar_screenshots(self, perceptual_hash: int) -> list[SavedScreenshotInfo]:
        if not self._saved_screenshots:
            return []

        threshold = self._similarity_bit_threshold()
        if threshold == 0:
            return []

        similar: list[SavedScreenshotInfo] = []
        for info in self._saved_screenshots.values():
            if self._are_hashes_similar(info.perceptual_hash, perceptual_hash):
                similar.append(info)
        return similar

    def _are_hashes_similar(self, hash_a: int, hash_b: int) -> bool:
        threshold = self._similarity_bit_threshold()
        if threshold == 0:
            return False
        return (hash_a ^ hash_b).bit_count() <= threshold

    def _similarity_bit_threshold(self) -> int:
        total_bits = max(1, self._hash_size * self._hash_size)
        threshold = int(total_bits * self._change_threshold)
        return max(0, min(total_bits, threshold))

    def _reset_pending(self, current_hash: str) -> None:
        self._pending_hash = None
        self._pending_perceptual_hash = None
        self._pending_count = 0
        self._last_hash = current_hash

    def _load_existing_hashes(self, target_dir: Path) -> None:
        """Load hashes from existing PNG files in the target directory to prevent duplicates."""
        assert Image is not None
        
        if not target_dir.exists():
            return
        
        existing_files = list(target_dir.glob("*.png"))
        if not existing_files:
            return
        
        logging.info("既存のスクリーンショット %d 枚からハッシュを読み込んでいます...", len(existing_files))
        
        for file_path in sorted(existing_files):
            try:
                with Image.open(file_path) as img:
                    exact_hash = self._compute_exact_hash(img)
                    perceptual_hash = self._compute_perceptual_hash(img)
            except Exception:
                logging.warning("ハッシュ読み込みエラー: %s", file_path)
                continue

            if exact_hash in self._saved_screenshots:
                logging.info("既存の重複スクリーンショットを削除します: %s", file_path)
                self._delete_file_safely(file_path)
                continue

            self._saved_screenshots[exact_hash] = SavedScreenshotInfo(
                path=file_path,
                exact_hash=exact_hash,
                perceptual_hash=perceptual_hash,
            )

        removed_count = self._prune_existing_similar_screenshots()
        logging.info("既存ハッシュ %d 件を読み込みました。", len(self._saved_screenshots))
        if removed_count:
            logging.info("類似スクリーンショット %d 件を削除しました。", removed_count)

    def _emit_status(self) -> None:
        status = self.status
        callback = self._status_callback
        if callback is not None:
            try:
                callback(status)
            except Exception:  # pragma: no cover - defensive
                logging.exception("スクリーンショットステータスコールバックの実行に失敗しました。")

    def _prepare_for_new_screenshot(self, current_hash: str, perceptual_hash: int) -> None:
        to_remove: dict[str, SavedScreenshotInfo] = {}

        existing = self._saved_screenshots.get(current_hash)
        if existing is not None:
            to_remove[existing.exact_hash] = existing

        for info in self._find_similar_screenshots(perceptual_hash):
            to_remove[info.exact_hash] = info

        if to_remove:
            self._remove_saved_screenshots(list(to_remove.values()))

    def _remove_saved_screenshots(self, infos: list[SavedScreenshotInfo]) -> None:
        if not infos:
            return

        removed_any = False
        for info in infos:
            existing = self._saved_screenshots.pop(info.exact_hash, None)
            if existing is None:
                continue

            removed_any = True
            deleted = self._delete_file_safely(existing.path)
            if deleted:
                logging.debug("類似スクリーンショットを削除しました: %s", existing.path)
            else:
                logging.warning("類似スクリーンショットの削除に失敗しました: %s", existing.path)

            with self._status_lock:
                if self._last_screenshot_path == existing.path:
                    self._last_screenshot_path = None

        if removed_any:
            self._emit_status()

    def _prune_existing_similar_screenshots(self) -> int:
        if not self._saved_screenshots:
            return 0

        infos = list(self._saved_screenshots.values())
        to_remove: dict[str, SavedScreenshotInfo] = {}

        for idx, candidate in enumerate(infos):
            for prior in infos[:idx]:
                if self._are_hashes_similar(candidate.perceptual_hash, prior.perceptual_hash):
                    to_remove[candidate.exact_hash] = candidate
                    break

        if not to_remove:
            return 0

        self._remove_saved_screenshots(list(to_remove.values()))
        return len(to_remove)

    def _delete_file_safely(self, path: Path) -> bool:
        try:
            path.unlink(missing_ok=True)
            return True
        except FileNotFoundError:
            return True
        except Exception:
            logging.exception("スクリーンショット削除中にエラーが発生しました: %s", path)
            return False
