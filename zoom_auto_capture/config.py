from __future__ import annotations

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
AUDIO_DIR = OUTPUT_DIR / "audio"
AUDIO_SAMPLE_RATE = 44_100
AUDIO_CHANNELS = 2
AUDIO_BLOCK_SIZE = 2048
ZOOM_PROCESS_NAMES = ("Zoom.exe", "zoom.us")
ZOOM_CHECK_INTERVAL_MS = 2_000

SILENCE_THRESHOLD_DB = -45.0
SILENCE_RESUME_DB = -40.0
SILENCE_MIN_DURATION = 3.0
VU_METER_MIN_DB = -60.0
VU_METER_MAX_DB = 0.0

MEETING_TITLE_MAX_LENGTH = 60
DEFAULT_MEETING_SLUG = "no_title"


def ensure_directories() -> None:
    """Ensure runtime output directories exist."""
    for path in (OUTPUT_DIR, AUDIO_DIR):
        path.mkdir(parents=True, exist_ok=True)
