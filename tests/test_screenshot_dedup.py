import logging
from pathlib import Path

import pytest

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from zoom_auto_capture.screenshot import SavedScreenshotInfo, ScreenshotCapture


@pytest.fixture
def capture(tmp_path, monkeypatch):
    cap = ScreenshotCapture(
        output_dir=tmp_path,
        check_interval=0.1,
        change_threshold=1.0,
        hash_size=8,
        stability_samples=1,
        stability_interval=0.1,
    )
    monkeypatch.setattr(logging, "debug", lambda *args, **kwargs: None)
    monkeypatch.setattr(logging, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(logging, "warning", lambda *args, **kwargs: None)
    return cap


def _create_image(path: Path, color: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (16, 16), color)
    image.save(path)


def test_load_existing_hashes_removes_exact_duplicates(tmp_path, capture):
    target_dir = tmp_path / "dup"
    target_dir.mkdir()

    img1 = target_dir / "img1.png"
    img2 = target_dir / "img2.png"
    _create_image(img1, (255, 0, 0))
    _create_image(img2, (255, 0, 0))

    capture._load_existing_hashes(target_dir)

    remaining_files = sorted(p.name for p in target_dir.glob("*.png"))
    assert remaining_files == ["img1.png"]
    assert len(capture._saved_screenshots) == 1
    assert next(iter(capture._saved_screenshots.values())).path == img1


def test_load_existing_hashes_removes_similar_images(tmp_path, capture):
    target_dir = tmp_path / "similar"
    target_dir.mkdir()

    img1 = target_dir / "base.png"
    img2 = target_dir / "variant.png"
    _create_image(img1, (0, 255, 0))
    _create_image(img2, (0, 240, 0))

    capture._load_existing_hashes(target_dir)

    remaining_files = sorted(p.name for p in target_dir.glob("*.png"))
    assert remaining_files == ["base.png"]
    assert len(capture._saved_screenshots) == 1
    assert next(iter(capture._saved_screenshots.values())).path == img1


def test_prepare_for_new_screenshot_purges_existing(tmp_path, capture, monkeypatch):
    existing_path = tmp_path / "existing.png"
    existing_path.write_bytes(b"dummy")

    info = SavedScreenshotInfo(path=existing_path, exact_hash="old", perceptual_hash=111)
    capture._saved_screenshots[info.exact_hash] = info
    capture._last_screenshot_path = existing_path

    monkeypatch.setattr(capture, "_find_similar_screenshots", lambda _hash: [info])

    capture._prepare_for_new_screenshot("new", 222)

    assert not existing_path.exists()
    assert info.exact_hash not in capture._saved_screenshots
    assert capture._last_screenshot_path is None
