from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path

from PIL import Image, ImageChops

from chemresearch_agent.domain.models import (
    BoundingBox,
    FigurePanelRecord,
    FigureRecord,
    FigureVisualProfile,
)

PANEL_LABEL = re.compile(r"\(([A-Z])\)", re.IGNORECASE)


class DeterministicFigureLayoutAnalyzer:
    """Conservative image analysis: uncertain panel boundaries always keep the whole figure."""

    def analyze(self, figure: FigureRecord, output_dir: Path) -> FigureVisualProfile:
        output_dir.mkdir(parents=True, exist_ok=True)
        image = Image.open(figure.asset_path).convert("RGB")
        trim_box = _content_box(image)
        trimmed = image.crop(trim_box)
        trimmed_path = output_dir / f"{figure.figure_id}-trimmed.png"
        trimmed.save(trimmed_path, optimize=True)
        labels = list(dict.fromkeys(label.upper() for label in PANEL_LABEL.findall(figure.caption)))
        is_scheme = figure.label.casefold().startswith("scheme")
        is_table = figure.label.casefold().startswith("table")
        raw_separators = _horizontal_separators(trimmed)
        ratio = trimmed.width / trimmed.height
        if is_table and ratio < 0.9 and not labels:
            table_candidates = [
                value
                for value in raw_separators
                if trimmed.height * 0.5 <= value <= trimmed.height * 0.82
            ]
            if table_candidates:
                labels = ["A", "B"]
                raw_separators = [
                    min(table_candidates, key=lambda value: abs(value - trimmed.height * 0.68))
                ]
        separators = (
            _select_panel_separators(raw_separators, len(labels) - 1, trimmed.height)
            if ratio < 0.9 and len(labels) in (2, 3)
            else raw_separators
        )
        panels: list[FigurePanelRecord] = []
        warnings: list[str] = []
        four_panel_separator = (
            _horizontal_whitespace_separator(trimmed)
            if ratio < 0.9 and len(labels) == 4
            else None
        )
        vertical_separator = (
            _vertical_whitespace_separator(trimmed)
            if ratio > 1.45 and len(labels) in (2, 3)
            else None
        )
        if four_panel_separator is not None:
            for panel_label, top, bottom in (
                ("A-B", 0, four_panel_separator),
                ("C-D", four_panel_separator, trimmed.height),
            ):
                panel = trimmed.crop((0, top, trimmed.width, bottom))
                panel_path = output_dir / f"{figure.figure_id}-panel-{panel_label}.png"
                panel.save(panel_path, optimize=True)
                panels.append(
                    FigurePanelRecord(
                        panel_label=panel_label,
                        asset_path=str(panel_path),
                        crop_box=BoundingBox(
                            x0=trim_box[0],
                            y0=trim_box[1] + top,
                            x1=trim_box[2],
                            y1=trim_box[1] + bottom,
                        ),
                    )
                )
        elif vertical_separator is not None:
            panel_regions = (
                (("A", 0, vertical_separator), ("B", vertical_separator, trimmed.width))
                if len(labels) == 2
                else (
                    ("A-B", 0, vertical_separator),
                    ("C", vertical_separator, trimmed.width),
                )
            )
            for panel_label, left, right in panel_regions:
                panel = trimmed.crop((left, 0, right, trimmed.height))
                panel_path = output_dir / f"{figure.figure_id}-panel-{panel_label}.png"
                panel.save(panel_path, optimize=True)
                panels.append(
                    FigurePanelRecord(
                        panel_label=panel_label,
                        asset_path=str(panel_path),
                        crop_box=BoundingBox(
                            x0=trim_box[0] + left,
                            y0=trim_box[1],
                            x1=trim_box[0] + right,
                            y1=trim_box[3],
                        ),
                    )
                )
        elif len(labels) in (2, 3) and len(separators) == len(labels) - 1:
            boundaries = [0, *separators, trimmed.height]
            for index, label in enumerate(labels):
                top, bottom = boundaries[index], boundaries[index + 1]
                if bottom - top < trimmed.height * 0.12:
                    panels = []
                    warnings.append("panel_boundary_too_small")
                    break
                panel = trimmed.crop((0, top, trimmed.width, bottom))
                panel_path = output_dir / f"{figure.figure_id}-panel-{label}.png"
                panel.save(panel_path, optimize=True)
                panels.append(
                    FigurePanelRecord(
                        panel_label=label,
                        asset_path=str(panel_path),
                        crop_box=BoundingBox(
                            x0=trim_box[0],
                            y0=trim_box[1] + top,
                            x1=trim_box[2],
                            y1=trim_box[1] + bottom,
                        ),
                    )
                )
        elif len(labels) in (2, 3):
            warnings.append("panel_boundary_unconfirmed")

        if panels and four_panel_separator is not None:
            layout = "two_panels_fill"
            confidence = 0.86
        elif panels and vertical_separator is not None:
            layout = "two_panels_fill" if len(labels) == 2 else "weighted_two_images"
            confidence = 0.84
        elif panels and len(panels) == 2 and ratio < 0.9:
            layout = "two_panels_fill"
            confidence = 0.9
        elif panels and len(panels) == 3 and ratio < 0.9:
            layout = "panel_triptych"
            confidence = 0.88
        elif len(labels) >= 2:
            layout = "multipanel_full"
            confidence = 0.82 if labels else 0.7
        elif is_scheme or is_table:
            layout = "image_full"
            confidence = 0.9
        elif ratio < 1.45:
            layout = "single_with_callout"
            confidence = 0.72
        else:
            layout = "image_full"
            confidence = 0.78
        if layout == "two_panels_fill" and len(panels) == 2:
            panels = _pad_panels_for_top_alignment(panels, output_dir)
        density = (trimmed.width * trimmed.height) / (image.width * image.height)
        return FigureVisualProfile(
            figure_id=figure.figure_id,
            trimmed_asset_path=str(trimmed_path),
            original_width=image.width,
            original_height=image.height,
            effective_width=trimmed.width,
            effective_height=trimmed.height,
            content_density=density,
            caption_panel_labels=labels,
            detected_separators=separators,
            panels=panels,
            recommended_layout=layout,
            confidence=confidence,
            warnings=warnings,
        )


def _pad_panels_for_top_alignment(
    panels: list[FigurePanelRecord], output_dir: Path
) -> list[FigurePanelRecord]:
    """Use equal canvases so contain-fit preserves a shared top edge.

    PowerPoint-style contain placement centers short images vertically. Padding
    at the bottom keeps unequal source panels top-aligned without stretching.
    """
    images = [Image.open(panel.asset_path).convert("RGB") for panel in panels]
    width = max(image.width for image in images)
    height = max(image.height for image in images)
    aligned: list[FigurePanelRecord] = []
    for panel, image in zip(panels, images, strict=True):
        canvas = Image.new("RGB", (width, height), "white")
        canvas.paste(image, (0, 0))
        path = output_dir / f"aligned-{Path(panel.asset_path).name}"
        canvas.save(path, optimize=True)
        aligned.append(panel.model_copy(update={"asset_path": str(path)}))
    return aligned


def _content_box(image: Image.Image) -> tuple[int, int, int, int]:
    background = Image.new("RGB", image.size, "white")
    difference = ImageChops.difference(image, background).convert("L")
    mask = difference.point(lambda value: 255 if value > 12 else 0)
    bbox = mask.getbbox()
    if bbox is None:
        return (0, 0, image.width, image.height)
    margin = max(8, min(image.width, image.height) // 100)
    return (
        max(0, bbox[0] - margin),
        max(0, bbox[1] - margin),
        min(image.width, bbox[2] + margin),
        min(image.height, bbox[3] + margin),
    )


def _horizontal_separators(image: Image.Image) -> list[int]:
    gray = image.convert("L")
    pixels = gray.load()
    candidates: list[int] = []
    edge = max(6, image.height // 50)
    for y in range(edge, image.height - edge):
        dark = sum(1 for x in range(image.width) if pixels[x, y] < 210)
        if dark / image.width >= 0.62:
            candidates.append(y)
    groups: list[list[int]] = []
    for value in candidates:
        if not groups or value - groups[-1][-1] > 4:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [group[len(group) // 2] for group in groups]


def _select_panel_separators(candidates: list[int], count: int, height: int) -> list[int]:
    if count <= 0 or len(candidates) < count:
        return candidates
    best: tuple[int, ...] | None = None
    best_score = -1.0
    for choice in combinations(candidates, count):
        segments = [
            choice[0],
            *(choice[index + 1] - choice[index] for index in range(count - 1)),
            height - choice[-1],
        ]
        minimum = min(segments)
        if minimum < height * 0.12:
            continue
        score = minimum - (max(segments) - minimum) * 0.08
        if score > best_score:
            best, best_score = choice, score
    return list(best) if best else candidates


def _vertical_whitespace_separator(image: Image.Image) -> int | None:
    gray = image.convert("L")
    pixels = gray.load()
    start, end = int(image.width * 0.35), int(image.width * 0.65)
    candidates = []
    for x in range(start, end):
        ink = sum(1 for y in range(image.height) if pixels[x, y] < 235)
        if ink / image.height <= 0.025:
            candidates.append(x)
    groups: list[list[int]] = []
    for value in candidates:
        if not groups or value - groups[-1][-1] > 1:
            groups.append([value])
        else:
            groups[-1].append(value)
    groups = [group for group in groups if len(group) >= max(5, image.width // 150)]
    if not groups:
        return None
    group = max(groups, key=len)
    return group[len(group) // 2]


def _horizontal_whitespace_separator(image: Image.Image) -> int | None:
    """Find a broad, low-ink band near mid-height for a conservative 2+2 split."""
    gray = image.convert("L")
    pixels = gray.load()
    start, end = int(image.height * 0.38), int(image.height * 0.62)
    candidates = []
    for y in range(start, end):
        ink = sum(1 for x in range(image.width) if pixels[x, y] < 235)
        if ink / image.width <= 0.018:
            candidates.append(y)
    groups: list[list[int]] = []
    for value in candidates:
        if not groups or value - groups[-1][-1] > 1:
            groups.append([value])
        else:
            groups[-1].append(value)
    groups = [group for group in groups if len(group) >= max(8, image.height // 120)]
    if not groups:
        return None
    group = max(
        groups,
        key=lambda values: (
            -abs(values[len(values) // 2] - image.height * 0.45),
            len(values),
        ),
    )
    return group[len(group) // 2]
