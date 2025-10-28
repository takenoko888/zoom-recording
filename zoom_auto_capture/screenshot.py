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


@dataclass(frozen=True)
class ScreenshotStatus:
    is_running: bool
    screenshot_count: int
    last_screenshot_path: Optional[Path]
    meeting_title: str


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
        self._saved_hashes: set[str] = set()
        self._pending_hash: Optional[str] = None
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
        self._saved_hashes.clear()

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
            monitor = sct.monitors[1]  # Primary monitor
            while not self._stop_event.is_set():
                start_time = time.perf_counter()
                try:
                    self._capture_and_check_stability(sct, monitor)
                except Exception:
                    logging.exception("スクリーンショット取得中にエラーが発生しました。")

                elapsed = time.perf_counter() - start_time
                sleep_time = max(0.0, self._stability_interval - elapsed)
                if self._stop_event.wait(timeout=sleep_time):
                    break

    def _capture_and_check_stability(self, sct, monitor: dict) -> None:
        """Capture and wait for screen stability before saving."""
        assert Image is not None

        raw = sct.grab(monitor)
        image = Image.frombytes("RGB", raw.size, raw.rgb)

        # Compute cryptographic hash for exact duplicate detection
        current_hash = self._compute_hash(image)

        # Already saved check
        if current_hash in self._saved_hashes:
            # Reset pending counter since we've seen this before
            self._pending_hash = None
            self._pending_count = 0
            self._last_hash = current_hash
            return

        # Stability check: require N consecutive identical hashes
        if self._pending_hash == current_hash:
            self._pending_count += 1
            if self._pending_count >= self._stability_samples:
                # Screen is stable - save it
                self._save_screenshot(image, current_hash)
                self._pending_hash = None
                self._pending_count = 0
        else:
            # Hash changed - restart stability counter
            self._pending_hash = current_hash
            self._pending_count = 1

    def _save_screenshot(self, image, current_hash: str) -> None:
        """Save a stable screenshot."""
        timestamp = dt.datetime.now()
        filename = f"screenshot_{timestamp.strftime('%H%M%S_%f')}.png"
        target_dir = self._prepare_output_directory()
        screenshot_path = target_dir / filename

        image.save(screenshot_path)

        with self._status_lock:
            self._screenshot_count += 1
            self._last_screenshot_path = screenshot_path

        self._last_hash = current_hash
        self._saved_hashes.add(current_hash)
        logging.debug("新しい安定画面を保存しました: %s", screenshot_path)
        self._emit_status()

    def _compute_hash(self, image) -> str:
        """Compute a cryptographic hash of the image for exact duplicate detection."""
        assert Image is not None
        # Use SHA256 for exact matching - guarantees no duplicates
        # Convert to consistent format before hashing
        normalized = image.resize((1920, 1080), Image.Resampling.LANCZOS).convert("RGB")
        image_bytes = normalized.tobytes()
        return hashlib.sha256(image_bytes).hexdigest()

    def _load_existing_hashes(self, target_dir: Path) -> None:
        """Load hashes from existing PNG files in the target directory to prevent duplicates."""
        assert Image is not None
        
        if not target_dir.exists():
            return
        
        existing_files = list(target_dir.glob("*.png"))
        if not existing_files:
            return
        
        logging.info("既存のスクリーンショット %d 枚からハッシュを読み込んでいます...", len(existing_files))
        
        for file_path in existing_files:
            try:
                with Image.open(file_path) as img:
                    img_hash = self._compute_hash(img)
                    self._saved_hashes.add(img_hash)
            except Exception:
                logging.warning("ハッシュ読み込みエラー: %s", file_path)
                continue
        
        logging.info("既存ハッシュ %d 件を読み込みました。", len(self._saved_hashes))

    def _emit_status(self) -> None:
        status = self.status
        callback = self._status_callback
        if callback is not None:
            try:
                callback(status)
            except Exception:  # pragma: no cover - defensive
                logging.exception("スクリーンショットステータスコールバックの実行に失敗しました。")
