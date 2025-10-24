from __future__ import annotations

import logging
import os
import tkinter as tk

from zoom_auto_capture import config
from zoom_auto_capture.font_utils import configure_japanese_font
from zoom_auto_capture.logging_utils import configure_logging
from zoom_auto_capture.ui import ZoomRecorderProgram


def main() -> None:
    config.ensure_directories()
    configure_logging()
    configure_japanese_font(os.environ.get("ZOOM_CAPTURE_JP_FONT"))

    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - GUI bootstrap
        logging.exception("Tkinter の初期化に失敗しました。")
        raise SystemExit(f"Tkinter の初期化に失敗しました: {exc}")

    app = ZoomRecorderProgram(root)
    logging.info("プログラムを起動しました。")
    print("プログラムを起動します。")
    root.mainloop()


if __name__ == "__main__":
    main()
