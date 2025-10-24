from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from . import config

try:
    import mss
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    mss = None

try:
    import pytesseract
    from pytesseract.pytesseract import TesseractNotFoundError
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pytesseract = None
    TesseractNotFoundError = RuntimeError


@dataclass(slots=True)
class OCRResult:
    text: str
    text_path: Path
    screenshot_path: Path
    captured_at: dt.datetime


class ZoomOCRWorker:
    def __init__(
        self,
        interval_seconds: float = config.SCREENSHOT_INTERVAL_SECONDS,
        region: Optional[dict[str, int]] = config.DEFAULT_SCREEN_REGION,
        text_dir: Path = config.TEXT_DIR,
        screenshot_dir: Path = config.SCREENSHOT_DIR,
        tesseract_cmd: Optional[str] = None,
    ) -> None:
        self._interval = interval_seconds
        self._region = region
        self._text_dir = text_dir
        self._screenshot_dir = screenshot_dir
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._tesseract_cmd = tesseract_cmd

        self._latest_result: Optional[OCRResult] = None
        self._lock = threading.Lock()
        self._tesseract_ready = False
        self._tesseract_error_reported = False

    @property
    def has_required_modules(self) -> bool:
        return mss is not None and pytesseract is not None

    @property
    def is_available(self) -> bool:
        if not self.has_required_modules:
            return False
        return self._tesseract_ready or self._ensure_tesseract_ready(log_error=False)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def latest_result(self) -> Optional[OCRResult]:
        with self._lock:
            return self._latest_result

    @property
    def tesseract_ready(self) -> bool:
        if not self.has_required_modules:
            return False
        return self._tesseract_ready or self._ensure_tesseract_ready(log_error=False)

    def start(self) -> bool:
        if not self.has_required_modules:
            logging.warning("OCR の依存パッケージが見つからないため、OCR 処理をスキップします。")
            return False
        if not self._ensure_tesseract_ready():
            return False
        if self.is_running:
            logging.debug("ZoomOCRWorker is already running.")
            return True

        self._text_dir.mkdir(parents=True, exist_ok=True)
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="ZoomOCRWorker", daemon=True)
        self._thread.start()
        logging.info("OCR 取得を開始しました。")
        return True

    def stop(self) -> None:
        if not self.is_running:
            return
        self._stop_event.set()
        assert self._thread is not None
        self._thread.join(timeout=max(2, int(self._interval * 2)))
        self._thread = None
        logging.info("OCR 取得を終了しました。")

    def close(self) -> None:
        self.stop()

    def _ensure_tesseract_ready(self, *, log_error: bool = True) -> bool:
        if not self.has_required_modules:
            return False
        assert pytesseract is not None

        if self._tesseract_ready:
            return True

        if self._tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self._tesseract_cmd

        try:
            pytesseract.get_tesseract_version()
        except (FileNotFoundError, TesseractNotFoundError):
            if log_error and not self._tesseract_error_reported:
                logging.error(
                    "Tesseract の実行ファイルが見つからないため OCR を利用できません。"
                    "Tesseract をインストールするか、環境変数 TESSERACT_CMD でパスを指定してください。"
                )
                self._tesseract_error_reported = True
            self._tesseract_ready = False
            return False

        self._tesseract_ready = True
        self._tesseract_error_reported = False
        return True

    def _run_loop(self) -> None:
        assert mss is not None and pytesseract is not None
        if self._tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self._tesseract_cmd

        with mss.mss() as sct:
            while not self._stop_event.is_set():
                start_time = time.perf_counter()
                try:
                    result = self._capture_once(sct)
                    with self._lock:
                        self._latest_result = result
                except (FileNotFoundError, TesseractNotFoundError):
                    self._handle_tesseract_failure()
                    break
                except Exception:
                    logging.exception("OCR 取得中にエラーが発生しました。")

                elapsed = time.perf_counter() - start_time
                sleep_time = max(0.0, self._interval - elapsed)
                if self._stop_event.wait(timeout=sleep_time):
                    break

    def _capture_once(self, sct: Any) -> OCRResult:
        timestamp = dt.datetime.now()
        file_name = timestamp.strftime("%Y%m%d_%H%M%S")

        if self._region is None:
            monitor = sct.monitors[1]
        else:
            monitor = self._region

        raw = sct.grab(monitor)
        image = Image.frombytes("RGB", raw.size, raw.rgb)
        grayscale = image.convert("L")

        screenshot_path = self._screenshot_dir / f"zoom_capture_{file_name}.png"
        grayscale.save(screenshot_path)

        text = pytesseract.image_to_string(grayscale, lang="jpn+eng")

        text_path = self._text_dir / f"zoom_capture_{file_name}.txt"
        text_path.write_text(text, encoding="utf-8")

        logging.debug("OCR 結果を保存しました: %s", text_path)
        return OCRResult(text=text, text_path=text_path, screenshot_path=screenshot_path, captured_at=timestamp)

    def _handle_tesseract_failure(self) -> None:
        self._tesseract_ready = False
        if not self._tesseract_error_reported:
            logging.error(
                "Tesseract が見つからないため OCR を停止しました。Tesseract をインストールし再度お試しください。"
            )
            self._tesseract_error_reported = True
        self._stop_event.set()


