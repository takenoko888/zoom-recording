from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

try:
    import matplotlib
    from matplotlib import font_manager as fm
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    matplotlib = None
    fm = None


_JAPANESE_FONT_CANDIDATES: tuple[str, ...] = (
    "Yu Gothic",
    "Yu Gothic UI",
    "Meiryo",
    "MS Gothic",
    "Noto Sans CJK JP",
    "Noto Sans JP",
    "IPAexGothic",
)


def _find_font_from_candidates(candidates: Iterable[str]) -> str | None:
    if fm is None:
        return None

    system_fonts = {Path(font_path).stem.lower(): font_path for font_path in fm.findSystemFonts()}  # type: ignore[arg-type]
    for candidate in candidates:
        key = candidate.lower().replace(" ", "")
        for name, path in system_fonts.items():
            if key in name.replace(" ", ""):
                return path
    return None


def configure_japanese_font(explicit_font_path: str | None = None) -> None:
    if matplotlib is None or fm is None:
        logging.warning("matplotlib が見つからないため、フォント設定をスキップします。")
        return

    target_font = explicit_font_path or _find_font_from_candidates(_JAPANESE_FONT_CANDIDATES)
    if not target_font:
        logging.warning("日本語フォントが見つかりません。日本語の表示に問題が生じる可能性があります。")
        print("日本語フォントが見つかりません。日本語の表示に問題が生じる可能性があります。")
        return

    font_prop = fm.FontProperties(fname=target_font)
    matplotlib.rcParams["font.family"] = font_prop.get_name()
    logging.info("日本語フォントを設定しました: %s", target_font)
    print(f"日本語フォントを設定しました: {target_font}")
