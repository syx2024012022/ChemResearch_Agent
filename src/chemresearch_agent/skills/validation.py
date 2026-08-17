from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from chemresearch_agent.domain.models import (
    PresentationArtifact,
    PresentationRequirements,
    SlideContent,
    SlidePlan,
    ValidationIssue,
    ValidationReport,
)

from .templates import BuiltinTemplateRegistry


class DeterministicPresentationValidator:
    minimum_visual_coverage = 0.25
    content_title_max_characters = 54
    cover_title_max_characters = 150

    def __init__(self) -> None:
        self._templates = BuiltinTemplateRegistry()

    def validate(
        self,
        plan: SlidePlan,
        contents: list[SlideContent],
        artifact: PresentationArtifact,
        requirements: PresentationRequirements | None = None,
    ) -> ValidationReport:
        issues: list[ValidationIssue] = []
        origins = [content.origin_plan_slide_id or content.slide_id for content in contents]
        collapsed_origins = list(dict.fromkeys(origins))
        if [item.slide_id for item in plan.slides] != collapsed_origins:
            issues.append(
                ValidationIssue(
                    code="plan_content_mismatch", message="规划项被遗漏或页面顺序不一致"
                )
            )
        if requirements and requirements.min_slide_count is not None:
            below_minimum = len(contents) < requirements.min_slide_count
            if below_minimum:
                issues.append(
                    ValidationIssue(code="slide_range", message="自动拆页后的页数超出用户范围")
                )
        if artifact.slide_count != len(contents):
            issues.append(ValidationIssue(code="slide_count", message="PPTX 页数与内容页数不一致"))
        if not Path(artifact.pptx_path).exists():
            issues.append(ValidationIssue(code="missing_pptx", message="PPTX 文件不存在"))
        if requirements and requirements.prefer_visual_dominance:
            issues.extend(self._validate_visual_coverage(contents, artifact))
        for layout_path in artifact.layout_paths:
            layout = json.loads(Path(layout_path).read_text(encoding="utf-8"))
            elements = layout.get("elements", [])
            for element in elements:
                bbox = element.get("bbox")
                if bbox and (
                    bbox[0] < 0
                    or bbox[1] < 0
                    or bbox[0] + bbox[2] > 1280
                    or bbox[1] + bbox[3] > 720
                ):
                    issues.append(
                        ValidationIssue(
                            code="canvas_overflow",
                            message=element.get("name", "unnamed element"),
                            slide_id=Path(layout_path).stem,
                        )
                    )
                if (
                    _is_main_title(element.get("name", ""))
                    and element.get("textLayout", {}).get("lineCount", 1)
                    > (2 if Path(layout_path).stem == "slide-01.layout" else 1)
                ):
                    issues.append(
                        ValidationIssue(
                            code="title_wrapped",
                            message=element.get("text", ""),
                            slide_id=Path(layout_path).stem,
                        )
                    )
        for content in contents:
            title_limit = (
                self.cover_title_max_characters
                if content.template_id == "title_paper_toc"
                else self.content_title_max_characters
            )
            if len(content.title) > title_limit:
                issues.append(
                    ValidationIssue(
                        code="title_too_long",
                        message=f"标题超过 {title_limit} 个字符，应压缩措辞而非换行",
                        slide_id=content.slide_id,
                    )
                )
            template = self._templates.get(content.template_id)
            allowed = {slot.name: slot for slot in template.slots}
            present_slots = {block.slot for block in content.blocks}
            for slot in template.slots:
                if slot.required and slot.name not in present_slots:
                    issues.append(
                        ValidationIssue(
                            code="missing_required_slot",
                            message=slot.name,
                            slide_id=content.slide_id,
                        )
                    )
            for block in content.blocks:
                slot = allowed.get(block.slot)
                if slot is None:
                    issues.append(
                        ValidationIssue(
                            code="unknown_slot", message=block.slot, slide_id=content.slide_id
                        )
                    )
                if (
                    slot
                    and block.text
                    and slot.max_characters
                    and len(block.text) > slot.max_characters
                ):
                    issues.append(
                        ValidationIssue(
                            code="text_overflow", message=block.slot, slide_id=content.slide_id
                        )
                    )
                if block.asset_path and not Path(block.asset_path).exists():
                    issues.append(
                        ValidationIssue(
                            code="missing_asset",
                            message=block.asset_path,
                            slide_id=content.slide_id,
                        )
                    )
                if (block.panel_label or block.crop_box) and not block.figure_id:
                    issues.append(
                        ValidationIssue(
                            code="untraceable_panel",
                            message=block.slot,
                            slide_id=content.slide_id,
                        )
                    )
            if "[Sources]" not in (content.speaker_notes or ""):
                issues.append(
                    ValidationIssue(
                        code="missing_sources",
                        message="speaker notes 缺少来源",
                        slide_id=content.slide_id,
                    )
                )
        return ValidationReport(passed=not issues, issues=issues)

    def _validate_visual_coverage(
        self,
        contents: list[SlideContent],
        artifact: PresentationArtifact,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for index, (content, preview_path) in enumerate(
            zip(contents, artifact.preview_paths, strict=False),
            start=1,
        ):
            if index == 1 or content.template_id == "title_paper_toc":
                continue
            coverage = _visual_coverage(Path(preview_path))
            if coverage is None:
                continue
            if coverage < self.minimum_visual_coverage:
                issues.append(
                    ValidationIssue(
                        code="insufficient_visual_coverage",
                        message=(
                            f"白色内容区有效视觉覆盖不足: {coverage:.3f} "
                            f"< {self.minimum_visual_coverage:.3f}"
                        ),
                        slide_id=content.slide_id,
                    )
                )
        return issues


def _is_main_title(name: str) -> bool:
    return re.fullmatch(r"title-\d+", name) is not None


def _visual_coverage(preview_path: Path) -> float | None:
    """Measure visible body coverage rather than image-container dimensions.

    For each row in the white content region, measure the horizontal span of
    non-white pixels. Averaging across all body rows penalizes both narrow
    portrait figures and short wide figures surrounded by excessive whitespace.
    """
    try:
        image = Image.open(preview_path).convert("RGB")
    except (FileNotFoundError, UnidentifiedImageError, OSError):
        return None
    if image.width < 100 or image.height < 100:
        return None
    left = round(image.width * 20 / 1280)
    right = round(image.width * 1260 / 1280)
    top = round(image.height * 95 / 720)
    bottom = round(image.height * 665 / 720)
    body = image.crop((left, top, right, bottom))
    pixels = body.load()
    row_spans: list[float] = []
    for y in range(body.height):
        ink_x = [x for x in range(body.width) if min(pixels[x, y]) < 235]
        if len(ink_x) < 3:
            row_spans.append(0.0)
        else:
            row_spans.append((ink_x[-1] - ink_x[0] + 1) / body.width)
    return sum(row_spans) / max(1, body.height)
