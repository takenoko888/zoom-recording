from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from . import config
from .audio import AudioRecorder, AudioStatus
from .process_utils import get_zoom_meeting_title, is_zoom_running, sanitize_meeting_title, slugify_title
from .screenshot import ScreenshotCapture, ScreenshotStatus


class ZoomRecorderProgram:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Zoom 自動取得")
        self.root.protocol("WM_DELETE_WINDOW", self.on_quit)

        self.audio = AudioRecorder()
        self.audio.register_status_callback(self._handle_audio_status)

        self.screenshot = ScreenshotCapture()
        self.screenshot.register_status_callback(self._handle_screenshot_status)

        self._monitoring = False
        self._zoom_running = False
        self._audio_warning_shown = False
        self._screenshot_warning_shown = False
        self._latest_audio_status = self.audio.status
        self._latest_screenshot_status = self.screenshot.status
        self._last_meeting_title = None

        self._status_var = tk.StringVar(value="停止中")
        self._audio_var = tk.StringVar(value="音声: 停止")
        self._zoom_var = tk.StringVar(value="Zoom: 未検出")
        self._meeting_title_var = tk.StringVar(value="会議タイトル: 未検出")
        self._duration_var = tk.StringVar(value="録音時間: 00:00:00 / 00:00:00")
        self._screenshot_var = tk.StringVar(value="スクリーンショット: 0 枚")

        self._build_layout()
        self._schedule_status_refresh()
        self._schedule_zoom_check()
        self.root.after(200, self._auto_start_capture)

    def _build_layout(self) -> None:
        padding = {"padx": 12, "pady": 8}

        title = ttk.Label(self.root, text="Zoom 自動取得", font=("Segoe UI", 16, "bold"))
        title.grid(row=0, column=0, columnspan=3, sticky="w", **padding)

        ttk.Label(self.root, textvariable=self._status_var, font=("Segoe UI", 12)).grid(
            row=1, column=0, columnspan=3, sticky="w", **padding
        )
        ttk.Label(self.root, textvariable=self._audio_var).grid(row=2, column=0, columnspan=3, sticky="w", **padding)
        ttk.Label(self.root, textvariable=self._zoom_var).grid(row=3, column=0, columnspan=3, sticky="w", **padding)
        ttk.Label(self.root, textvariable=self._meeting_title_var).grid(
            row=4, column=0, columnspan=3, sticky="w", **padding
        )
        ttk.Label(self.root, textvariable=self._duration_var).grid(row=5, column=0, columnspan=3, sticky="w", **padding)
        ttk.Label(self.root, textvariable=self._screenshot_var).grid(row=6, column=0, columnspan=3, sticky="w", **padding)

        ttk.Label(self.root, text="音声レベル").grid(row=7, column=0, sticky="w", **padding)
        self._vu_meter = ttk.Progressbar(self.root, orient="horizontal", mode="determinate", maximum=100)
        self._vu_meter.grid(row=7, column=1, columnspan=2, sticky="ew", **padding)

        self.start_button = ttk.Button(self.root, text="開始", command=self.start_capture)
        self.start_button.grid(row=8, column=0, sticky="ew", **padding)

        self.stop_button = ttk.Button(self.root, text="停止", command=self.stop_capture)
        self.stop_button.grid(row=8, column=1, sticky="ew", **padding)

        open_button = ttk.Button(self.root, text="出力フォルダを開く", command=self._open_output)
        open_button.grid(row=8, column=2, sticky="ew", **padding)

    def start_capture(self) -> None:
        self._start_monitor(auto=False)

    def _auto_start_capture(self) -> None:
        self._start_monitor(auto=True)

    def _start_monitor(self, *, auto: bool) -> None:
        if not self._monitoring:
            self._monitoring = True
            logging.info("Zoom 監視を開始しました。")
        else:
            logging.debug("Zoom 監視は既に有効です。")

        if not self.audio.is_available:
            self._status_var.set("音声ライブラリ未検出")
            if not self._audio_warning_shown:
                messagebox.showerror(
                    "音声ライブラリが必要です",
                    "sounddevice / soundfile がインストールされていないため音声収録を開始できません。",
                )
                self._audio_warning_shown = True
            self._monitoring = False
            return

        try:
            self._check_zoom_state(show_dialog=not auto)
        except Exception:
            logging.exception("自動取得の開始に失敗しました。")
            messagebox.showerror("エラー", "自動取得の開始に失敗しました。ログを確認してください。")

    def stop_capture(self) -> None:
        self._monitoring = False
        if self.audio.is_running:
            self.audio.stop()
        if self.screenshot.is_running:
            self.screenshot.stop()
        self._status_var.set("停止中")
        logging.info("自動取得を停止しました。")

    def _schedule_status_refresh(self) -> None:
        self._refresh_status()
        self.root.after(1000, self._schedule_status_refresh)

    def _refresh_status(self) -> None:
        self._audio_var.set(self._audio_status_text())
        self._zoom_var.set(self._zoom_status_text())
        status = self._latest_audio_status
        self._duration_var.set(self._format_duration_text(status))
        self._meeting_title_var.set(self._meeting_title_text(status.meeting_title))
        self._update_status_label_from_audio(status)
        self._update_vu_meter(status)
        
        screenshot_status = self._latest_screenshot_status
        self._screenshot_var.set(self._format_screenshot_text(screenshot_status))

    def _audio_status_text(self) -> str:
        if not self.audio.is_available:
            return "音声: 利用不可"
        status = self._latest_audio_status
        if status.stream_active:
            if status.writing_active:
                filename = status.file_path.name if status.file_path else "出力準備中"
                return f"音声: 録音中 ({filename})"
            return "音声: 無音で一時停止"
        return "音声: 停止"

    def _zoom_status_text(self) -> str:
        return "Zoom: 起動中" if self._zoom_running else "Zoom: 未検出"

    def _schedule_zoom_check(self) -> None:
        self._check_zoom_state(show_dialog=False)
        self.root.after(config.ZOOM_CHECK_INTERVAL_MS, self._schedule_zoom_check)

    def _check_zoom_state(self, *, show_dialog: bool) -> None:
        zoom_running = is_zoom_running()
        if zoom_running != self._zoom_running:
            message = "Zoom を検出しました。" if zoom_running else "Zoom を検出できなくなりました。"
            logging.info(message)

        self._zoom_running = zoom_running
        self._zoom_var.set(self._zoom_status_text())

        if zoom_running:
            meeting_title = get_zoom_meeting_title()
            if meeting_title:
                self._last_meeting_title = meeting_title
                self._meeting_title_var.set(self._meeting_title_text(meeting_title))

        if not self._monitoring:
            return

        if zoom_running:
            if not self.audio.is_running:
                self.audio.start(meeting_title=self._last_meeting_title)
                if self.audio.is_running:
                    logging.info("Zoom が起動したため音声収録を開始しました。")
                    self._status_var.set("Zoom起動中 – 録音中")
                else:
                    self._status_var.set("Zoom起動中 – 音声利用不可")
            else:
                self._status_var.set("Zoom起動中 – 録音中")
            
            # Start screenshot capture if available
            if not self.screenshot.is_running and self.screenshot.is_available:
                meeting_title_display = sanitize_meeting_title(self._last_meeting_title)
                if meeting_title_display == config.DEFAULT_MEETING_SLUG:
                    meeting_title_display = "未検出"
                meeting_title_slug = slugify_title(self._last_meeting_title)
                self.screenshot.start(meeting_title_display, meeting_title_slug)
                logging.info("Zoom が起動したためスクリーンショット取得を開始しました。")
            elif not self.screenshot.is_available and not self._screenshot_warning_shown:
                logging.warning("mss / Pillow が見つからないためスクリーンショット取得をスキップします。")
                self._screenshot_warning_shown = True
        else:
            if self.audio.is_running:
                self.audio.stop()
                logging.info("Zoom が終了したため音声収録を停止しました。")
            if self.screenshot.is_running:
                self.screenshot.stop()
                logging.info("Zoom が終了したためスクリーンショット取得を停止しました。")
            self._last_meeting_title = None
            self._meeting_title_var.set(self._meeting_title_text(None))
            self._status_var.set("Zoom待機中")
            if show_dialog:
                messagebox.showinfo(
                    "Zoom を起動してください",
                    "Zoom が起動していません。Zoom が起動すると自動的に音声収録を開始します。",
                )

    def _open_output(self) -> None:
        config.ensure_directories()
        webbrowser.open(config.OUTPUT_DIR.as_uri())

    def on_quit(self) -> None:
        try:
            self.stop_capture()
        finally:
            self.root.destroy()

    def _handle_audio_status(self, status: AudioStatus) -> None:
        self._latest_audio_status = status

    def _format_duration_text(self, status: AudioStatus) -> str:
        recorded = self._format_seconds(status.recorded_seconds)
        runtime = self._format_seconds(status.runtime_seconds)
        return f"録音時間: {recorded} / {runtime}"

    def _meeting_title_text(self, raw_title: str | None) -> str:
        title = sanitize_meeting_title(raw_title) if raw_title else config.DEFAULT_MEETING_SLUG
        if title == config.DEFAULT_MEETING_SLUG:
            display = "未検出"
        else:
            display = title
        return f"会議タイトル: {display}"

    def _format_seconds(self, seconds: float) -> str:
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{secs:02}"

    def _update_status_label_from_audio(self, status: AudioStatus) -> None:
        if not self._monitoring or not self._zoom_running:
            return
        if status.stream_active:
            if status.writing_active:
                self._status_var.set("Zoom起動中 – 録音中")
            else:
                self._status_var.set("Zoom起動中 – 無音で一時停止")

    def _update_vu_meter(self, status: AudioStatus) -> None:
        span = config.VU_METER_MAX_DB - config.VU_METER_MIN_DB
        if span <= 0:
            self._vu_meter["value"] = 0
            return
        level = max(config.VU_METER_MIN_DB, min(status.level_db, config.VU_METER_MAX_DB))
        ratio = (level - config.VU_METER_MIN_DB) / span
        self._vu_meter["value"] = max(0.0, min(100.0, ratio * 100))

    def _handle_screenshot_status(self, status: ScreenshotStatus) -> None:
        self._latest_screenshot_status = status

    def _format_screenshot_text(self, status: ScreenshotStatus) -> str:
        return f"スクリーンショット: {status.screenshot_count} 枚"
