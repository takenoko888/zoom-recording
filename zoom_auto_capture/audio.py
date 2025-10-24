from __future__ import annotations

import datetime as dt
import logging
import math
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import config
from .process_utils import get_zoom_meeting_title, sanitize_meeting_title, slugify_title

try:
    import sounddevice as sd
    import soundfile as sf
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    sd = None
    sf = None


@dataclass(frozen=True)
class AudioStatus:
    level_db: float
    stream_active: bool
    writing_active: bool
    recorded_seconds: float
    runtime_seconds: float
    file_path: Optional[Path]
    meeting_title: str


class AudioRecorder:
    def __init__(
        self,
        output_dir: Path = config.AUDIO_DIR,
        samplerate: int = config.AUDIO_SAMPLE_RATE,
        channels: int = config.AUDIO_CHANNELS,
        blocksize: int = config.AUDIO_BLOCK_SIZE,
        device: Optional[int | str] = None,
    ) -> None:
        self._output_dir = output_dir
        self._samplerate = samplerate
        self._channels = channels
        self._blocksize = blocksize
        self._device = device

        self._stream: Optional[sd.InputStream] = None  # type: ignore[assignment]
        self._stream_active = False
        self._writer_thread: Optional[threading.Thread] = None
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stop_event = threading.Event()
        self._current_file: Optional[Path] = None
        self._meeting_title_display = "未検出"
        self._meeting_title_slug = config.DEFAULT_MEETING_SLUG

        self._status_lock = threading.Lock()
        self._last_status = AudioStatus(
            level_db=config.VU_METER_MIN_DB,
            stream_active=False,
            writing_active=False,
            recorded_seconds=0.0,
            runtime_seconds=0.0,
            file_path=None,
            meeting_title=self._meeting_title_display,
        )
        self._status_callback: Optional[Callable[[AudioStatus], None]] = None

        self._active_frames = 0
        self._start_monotonic: Optional[float] = None
        self._suspended = False
        self._silence_started_at: Optional[float] = None

    @property
    def is_available(self) -> bool:
        return sd is not None and sf is not None

    @property
    def is_running(self) -> bool:
        return self._stream_active

    @property
    def current_output(self) -> Optional[Path]:
        return self._current_file

    @property
    def meeting_title(self) -> str:
        return self._meeting_title_display

    @property
    def status(self) -> AudioStatus:
        with self._status_lock:
            return self._last_status

    def register_status_callback(self, callback: Callable[[AudioStatus], None]) -> None:
        self._status_callback = callback

    def start(self, meeting_title: Optional[str] = None) -> None:
        if not self.is_available:
            logging.warning("sounddevice / soundfile がインストールされていないため、音声取得をスキップします。")
            return
        if self.is_running:
            logging.debug("AudioRecorder is already running.")
            return

        title = meeting_title or get_zoom_meeting_title()
        sanitized_for_display = sanitize_meeting_title(title)
        if sanitized_for_display == config.DEFAULT_MEETING_SLUG:
            self._meeting_title_display = "未検出"
        else:
            self._meeting_title_display = sanitized_for_display
        self._meeting_title_slug = slugify_title(title)

        target_dir = self._prepare_output_directory()
        timestamp = dt.datetime.now()
        filename = f"zoom_audio_{timestamp.strftime('%H%M%S')}.wav"
        self._current_file = target_dir / filename

        self._reset_state_for_start()

        self._writer_thread = threading.Thread(target=self._writer_loop, name="AudioWriter", daemon=True)
        self._writer_thread.start()

        try:
            self._stream = sd.InputStream(
                samplerate=self._samplerate,
                channels=self._channels,
                blocksize=self._blocksize,
                device=self._device,
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception:
            logging.exception("音声ストリームの初期化に失敗しました。")
            self._stop_event.set()
            if self._writer_thread is not None:
                self._writer_thread.join(timeout=5)
                self._writer_thread = None
            return

        self._stream_active = True
        self._start_monotonic = time.monotonic()
        self._emit_status(config.VU_METER_MIN_DB)
        logging.info("音声収録を開始しました: %s", self._current_file)

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

        self._stream_active = False
        self._stop_event.set()
        if self._writer_thread is not None:
            self._writer_thread.join(timeout=5)
            self._writer_thread = None

        self._emit_status(config.VU_METER_MIN_DB)
        logging.info("音声収録を終了しました: %s", self._current_file)

    def close(self) -> None:
        self.stop()

    def _reset_state_for_start(self) -> None:
        self._stop_event.clear()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._active_frames = 0
        self._suspended = False
        self._silence_started_at = None
        self._stream_active = False
        self._start_monotonic = None

    def _prepare_output_directory(self) -> Path:
        today = dt.datetime.now().strftime("%Y%m%d")
        target_dir = self._output_dir / today / self._meeting_title_slug
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:  # type: ignore[override]
        if status:
            logging.warning("Audio stream status: %s", status)
        self._queue.put(indata.copy())

    def _writer_loop(self) -> None:
        assert sf is not None
        file_path = self._current_file
        if file_path is None:
            return

        with sf.SoundFile(
            file_path,
            mode="w",
            samplerate=self._samplerate,
            channels=self._channels,
            subtype="PCM_16",
        ) as file:
            while not self._stop_event.is_set() or not self._queue.empty():
                try:
                    block = self._queue.get(timeout=0.2)
                except queue.Empty:
                    self._emit_status(self.status.level_db)
                    continue

                level_db = self._compute_level_db(block)
                self._handle_silence(level_db)

                if not self._suspended:
                    file.write(block)
                    self._active_frames += block.shape[0]

                self._emit_status(level_db)

        self._emit_status(config.VU_METER_MIN_DB)

    def _compute_level_db(self, block: np.ndarray) -> float:
        if block.size == 0:
            return config.VU_METER_MIN_DB
        # Convert to mono for level calculation
        if block.ndim > 1:
            block = np.mean(block, axis=1)
        rms = float(np.sqrt(np.mean(np.square(block))))
        level = 20.0 * math.log10(rms + 1e-12)
        return max(config.VU_METER_MIN_DB, min(level, config.VU_METER_MAX_DB))

    def _handle_silence(self, level_db: float) -> None:
        now = time.monotonic()

        if level_db < config.SILENCE_THRESHOLD_DB:
            if self._silence_started_at is None:
                self._silence_started_at = now
            elif not self._suspended and now - self._silence_started_at >= config.SILENCE_MIN_DURATION:
                self._suspended = True
                logging.info("無音を検出したため録音を一時停止しました。")
        else:
            self._silence_started_at = None
            if self._suspended and level_db >= config.SILENCE_RESUME_DB:
                self._suspended = False
                logging.info("音声入力を検出したため録音を再開しました。")

    def _emit_status(self, level_db: float) -> None:
        stream_active = self._stream_active and not self._stop_event.is_set()
        writing_active = stream_active and not self._suspended
        recorded_seconds = self._active_frames / self._samplerate
        runtime_seconds = 0.0
        if self._start_monotonic is not None:
            runtime_seconds = max(0.0, time.monotonic() - self._start_monotonic)

        status = AudioStatus(
            level_db=level_db,
            stream_active=stream_active,
            writing_active=writing_active,
            recorded_seconds=recorded_seconds,
            runtime_seconds=runtime_seconds,
            file_path=self._current_file,
            meeting_title=self._meeting_title_display,
        )

        with self._status_lock:
            self._last_status = status

        callback = self._status_callback
        if callback is not None:
            try:
                callback(status)
            except Exception:  # pragma: no cover - defensive
                logging.exception("音声ステータスコールバックの実行に失敗しました。")

