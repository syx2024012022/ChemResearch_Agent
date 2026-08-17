from pathlib import Path

from PIL import Image, ImageDraw

from chemresearch_agent.skills.validation import _is_main_title, _visual_coverage


def _preview(
    path: Path,
    *,
    left: int,
    top: int,
    right: int,
    bottom: int,
    spacing: int = 26,
) -> None:
    image = Image.new("RGB", (1280, 720), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1279, 81), fill="#1F55A5")
    for y in range(top, bottom, spacing):
        draw.line((left, y, right, y), fill="black", width=3)
    image.save(path)


def test_visual_coverage_rejects_narrow_centered_body(tmp_path: Path) -> None:
    preview = tmp_path / "narrow.png"
    _preview(preview, left=430, top=150, right=850, bottom=620)
    coverage = _visual_coverage(preview)
    assert coverage is not None
    assert coverage < 0.25


def test_visual_coverage_accepts_page_filling_body(tmp_path: Path) -> None:
    preview = tmp_path / "filled.png"
    _preview(preview, left=70, top=115, right=1210, bottom=645, spacing=8)
    coverage = _visual_coverage(preview)
    assert coverage is not None
    assert coverage > 0.25


def test_title_wrap_gate_only_matches_numbered_main_titles() -> None:
    assert _is_main_title("title-1")
    assert _is_main_title("title-12")
    assert not _is_main_title("title-authors")
    assert not _is_main_title("title-publication")
