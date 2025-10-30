from __future__ import annotations

import logging
import re
from typing import Iterable, Optional, Sequence, Set

from . import config

try:
    import psutil
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    psutil = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency
    import win32gui
    import win32process
except ModuleNotFoundError:
    win32gui = None  # type: ignore[assignment]
    win32process = None  # type: ignore[assignment]


_psutil_warning_emitted = False
_win32_warning_emitted = False

_INVALID_CHARS_PATTERN = re.compile(r"[\\/:*?\"<>|]+")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def _normalize_name(name: str) -> str:
    return name.lower()


def _target_names(process_names: Iterable[str] | None = None) -> tuple[str, ...]:
    return tuple(_normalize_name(name) for name in (process_names or config.ZOOM_PROCESS_NAMES))


def _iter_zoom_processes(process_names: Iterable[str] | None = None) -> Sequence[object]:
    if psutil is None:  # pragma: no cover - optional dependency
        return []

    targets = _target_names(process_names)
    matches = []
    for proc in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            exe = (proc.info.get("exe") or "").split("\\")[-1].lower()
            cmdline = [part.split("\\")[-1].lower() for part in (proc.info.get("cmdline") or [])]
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

        if name in targets or exe in targets or any(entry in targets for entry in cmdline):
            matches.append(proc)
    return matches


def _collect_zoom_pids(process_names: Iterable[str] | None = None) -> Set[int]:
    return {proc.pid for proc in _iter_zoom_processes(process_names)}


def is_zoom_running(process_names: Iterable[str] | None = None) -> bool:
    """Return True when a Zoom process is currently running."""
    global _psutil_warning_emitted

    if psutil is None:
        if not _psutil_warning_emitted:
            logging.warning("psutil が見つからないため Zoom プロセスを監視できません。")
            _psutil_warning_emitted = True
        return False

    return bool(_collect_zoom_pids(process_names))


def get_zoom_meeting_title(process_names: Iterable[str] | None = None) -> Optional[str]:
    """Try to read the active Zoom meeting window title."""

    global _win32_warning_emitted

    if win32gui is None or win32process is None:
        if not _win32_warning_emitted:
            logging.debug("pywin32 が見つからないため Zoom のウィンドウタイトルを取得できません。")
            _win32_warning_emitted = True
        return None

    pids = _collect_zoom_pids(process_names)
    if not pids:
        return None

    titles: list[str] = []

    def _callback(hwnd: int, _param) -> bool:
        if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
            return True
        if win32gui.IsIconic(hwnd):
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid not in pids:
            return True
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return True
        titles.append(title)
        return True

    win32gui.EnumWindows(_callback, None)

    if not titles:
        return None

    # Choose the longest title assuming it carries meeting information
    titles.sort(key=len, reverse=True)
    return titles[0]


def sanitize_meeting_title(title: Optional[str]) -> str:
    if not title:
        return config.DEFAULT_MEETING_SLUG
    cleaned = _INVALID_CHARS_PATTERN.sub(" ", title).strip()
    cleaned = _WHITESPACE_PATTERN.sub(" ", cleaned)
    cleaned = cleaned.strip(" .")
    if not cleaned:
        return config.DEFAULT_MEETING_SLUG
    return cleaned


def slugify_title(title: Optional[str]) -> str:
    cleaned = sanitize_meeting_title(title)
    slug = _WHITESPACE_PATTERN.sub("_", cleaned)
    slug = re.sub(r"_+", "_", slug)
    if len(slug) > config.MEETING_TITLE_MAX_LENGTH:
        slug = slug[: config.MEETING_TITLE_MAX_LENGTH].rstrip("_-")
    return slug or config.DEFAULT_MEETING_SLUG


def get_zoom_screen_share_window() -> Optional[tuple[int, str]]:
    """
    Get the Zoom screen share window handle and title.
    Returns (hwnd, title) if screen share window is found, None otherwise.
    """
    global _win32_warning_emitted

    if win32gui is None or win32process is None:
        if not _win32_warning_emitted:
            logging.debug("pywin32 が見つからないため Zoom のウィンドウを取得できません。")
            _win32_warning_emitted = True
        return None

    pids = _collect_zoom_pids()
    if not pids:
        return None

    screen_share_windows: list[tuple[int, str]] = []

    def _callback(hwnd: int, _param) -> bool:
        if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
            return True
        if win32gui.IsIconic(hwnd):
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid not in pids:
            return True
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return True
        
        # Check if this is a screen share window
        # Common patterns: "画面を共有しています", "Screen Share", "画面の共有"
        share_keywords = ["画面を共有", "screen share", "画面の共有", "sharing screen"]
        if any(keyword in title.lower() for keyword in share_keywords):
            screen_share_windows.append((hwnd, title))
        
        return True

    win32gui.EnumWindows(_callback, None)

    if not screen_share_windows:
        return None

    # Return the first screen share window found
    return screen_share_windows[0]
