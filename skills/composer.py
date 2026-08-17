from __future__ import annotations

import re
from pathlib import Path

from chemresearch_agent.domain.enums import ClaimBasis, SlideType
from chemresearch_agent.domain.models import (
    ContentBlock,
    DocumentParseResult,
    EvidenceRef,
    LayoutDecision,
    PaperAnalysis,
    PresentationRequirements,
    SlideContent,
    SlidePlan,
)

from .figure_layout import DeterministicFigureLayoutAnalyzer
from .templates import BuiltinTemplateRegistry


class RuleBasedPresentationComposerSkill:
    name = "presentation_composer"
    version = "0.2.0"

    def __init__(self, templates=None, figure_analyzer=None) -> None:
        self._templates = templates or BuiltinTemplateRegistry()
        self._figure_analyzer = figure_analyzer or DeterministicFigureLayoutAnalyzer()

    def compose(
        self,
        plan: SlidePlan,
        analysis: PaperAnalysis,
        document: DocumentParseResult,
        requirements: PresentationRequirements,
        composition_asset_dir: Path | None = None,
    ) -> list[SlideContent]:
        asset_dir = composition_asset_dir or Path(".composition-assets")
        figures_by_source = {
            source_id: figure
            for figure in document.figures
            for source_id in [figure.caption_source_id, *figure.referenced_by_source_ids]
        }
        toc = next((f for f in document.figures if f.label == "TOC Graphic"), None)
        if requirements.title_include_toc_graphic and toc is None:
            toc = next(
                (figure for figure in document.figures if not figure.label.startswith("Table")),
                None,
            )
        resolved = []
        used_figure_ids: set[str] = set()
        for item in plan.slides:
            figures = _resolve_figures(item.source_refs, figures_by_source)
            fresh = [figure for figure in figures if figure.figure_id not in used_figure_ids]
            if fresh:
                figures = fresh
            if item.slide_type != SlideType.CONCLUSION:
                used_figure_ids.update(figure.figure_id for figure in figures)
            resolved.append((item, figures))
        result: list[SlideContent] = []
        for item, figures in resolved:
            if item.slide_type == SlideType.TITLE:
                result.append(self._title(item, analysis, toc, requirements))
                continue
            if requirements.require_visual_each_slide and not figures:
                raise ValueError(
                    f"{item.slide_id} would be text-only; every slide requires a visual asset"
                )
            profiles = [self._figure_analyzer.analyze(f, asset_dir / f.figure_id) for f in figures]
            if item.slide_type == SlideType.CONCLUSION and len(figures) > 1:
                figure, profile = _select_conclusion_hero(figures, profiles)
                figures, profiles = [figure], [profile]
            mechanism_overview = (
                item.slide_type == SlideType.REACTION_DESIGN
                and any(
                    term in figure.caption.casefold()
                    for figure in figures
                    for term in ("catalytic cycle", "proposed cycle")
                )
            )
            split = (
                len(figures) == 2
                and not mechanism_overview
                and _should_split(figures, profiles)
            )
            if split:
                for index, (figure, profile) in enumerate(zip(figures, profiles, strict=True)):
                    split_warnings = []
                    if (
                        requirements.max_slide_count
                        and len(plan.slides) + 1 > requirements.max_slide_count
                    ):
                        split_warnings.append("slide_limit_relaxed_for_layout_quality")
                    result.append(
                        self._visual(
                            item,
                            [figure],
                            [profile],
                            document,
                            analysis,
                            slide_id=f"{item.slide_id}-{chr(97 + index)}",
                            title=_caption_title(figure, item.key_message),
                            auto_split=True,
                            warnings=split_warnings,
                        )
                    )
            else:
                result.append(
                    self._visual(
                        item,
                        figures,
                        profiles,
                        document,
                        analysis,
                        slide_id=item.slide_id,
                        title=_display_title(
                            item.key_message,
                            figures,
                            requirements.language,
                            item.slide_type,
                        ),
                    )
                )
        return result

    def _title(self, item, analysis, toc, requirements) -> SlideContent:
        blocks = [ContentBlock(slot="message", text=item.key_message[:240])]
        if requirements.title_include_authors:
            blocks.append(ContentBlock(slot="authors", text=", ".join(analysis.metadata.authors)))
        if requirements.title_include_publication:
            publication = " · ".join(
                v
                for v in [
                    analysis.metadata.journal,
                    str(analysis.metadata.year) if analysis.metadata.year else None,
                    f"DOI: {analysis.metadata.doi}" if analysis.metadata.doi else None,
                ]
                if v
            )
            blocks.append(ContentBlock(slot="publication", text=publication))
        if requirements.title_include_toc_graphic and toc:
            blocks.append(
                ContentBlock(slot="toc_graphic", asset_path=toc.asset_path, figure_id=toc.figure_id)
            )
        return SlideContent(
            slide_id=item.slide_id,
            origin_plan_slide_id=item.slide_id,
            title=analysis.metadata.title,
            template_id="title_paper_toc",
            blocks=blocks,
            citations=item.source_refs,
            speaker_notes=(
                f"[Speaker Notes]\n{item.purpose}\n\n[Sources]\n"
                f"- Article metadata and {toc.label if toc else 'paper identity'}, "
                f"PDF p.{toc.page_number if toc else 1}"
            ),
            layout_decision=LayoutDecision(
                layout="title_paper_toc", reason="paper identity", confidence=1.0
            ),
        )

    def _visual(
        self,
        item,
        figures,
        profiles,
        document,
        analysis,
        *,
        slide_id,
        title,
        auto_split=False,
        warnings=None,
    ) -> SlideContent:
        warnings = list(warnings or [])
        panel_labels: list[str] = []
        if len(figures) == 1:
            figure, profile = figures[0], profiles[0]
            template_id = profile.recommended_layout
            panels = (
                profile.panels
                if template_id in {"two_panels_fill", "panel_triptych", "weighted_two_images"}
                else []
            )
            message = title
            if template_id == "single_with_callout":
                callout = _extract_callout(document, figure, title)
                if callout:
                    message = callout
                else:
                    template_id = "multipanel_full"
            blocks = [ContentBlock(slot="message", text=message[:240])]
            if panels:
                for index, panel in enumerate(panels):
                    blocks.append(
                        ContentBlock(
                            slot=f"figure_{index + 1}",
                            asset_path=panel.asset_path,
                            figure_id=figure.figure_id,
                            panel_label=panel.panel_label,
                            crop_box=panel.crop_box,
                        )
                    )
                panel_labels = [panel.panel_label for panel in panels]
            else:
                blocks.append(
                    ContentBlock(
                        slot="figure_1",
                        asset_path=profile.trimmed_asset_path,
                        figure_id=figure.figure_id,
                    )
                )
            confidence = profile.confidence
            warnings.extend(profile.warnings)
        else:
            captions = " ".join(f.caption.casefold() for f in figures)
            if (
                item.slide_type == SlideType.REACTION_DESIGN
                and any(term in captions for term in ("catalytic cycle", "proposed cycle"))
            ):
                template_id = "stacked_mechanism_overview"
            else:
                template_id = (
                    "weighted_two_images"
                    if any(_is_quantitative_plot(f.caption) for f in figures)
                    else "application_double"
                )
            blocks = [ContentBlock(slot="message", text=title[:240])]
            for index, (figure, profile) in enumerate(
                zip(figures[:2], profiles[:2], strict=True)
            ):
                blocks.append(
                    ContentBlock(
                        slot=f"figure_{index + 1}",
                        asset_path=profile.trimmed_asset_path,
                        figure_id=figure.figure_id,
                    )
                )
            confidence = min((p.confidence for p in profiles), default=0.7)
        sources = _sources(item.source_refs)
        inference = (
            "\n[Inference]\n本页包含分析性归纳。"
            if _has_inference(analysis, item.source_refs)
            else ""
        )
        return SlideContent(
            slide_id=slide_id,
            origin_plan_slide_id=item.slide_id,
            title=title[:100],
            template_id=template_id,
            blocks=blocks,
            citations=item.source_refs,
            speaker_notes=(
                f"[Speaker Notes]\n{item.purpose}\n\n{inference}\n\n[Sources]\n{sources}"
            ).strip(),
            layout_decision=LayoutDecision(
                layout=self._templates.get(template_id).layout,
                reason="deterministic figure geometry and caption analysis",
                figure_ids=[f.figure_id for f in figures],
                panel_labels=panel_labels,
                confidence=confidence,
                auto_split=auto_split,
            ),
            composition_warnings=list(dict.fromkeys(warnings)),
        )


def _resolve_figures(refs, mapping):
    result = []
    for ref in refs:
        figure = mapping.get(ref.source_id)
        if figure and figure.asset_path not in {item.asset_path for item in result}:
            result.append(figure)
    return result


def _should_split(figures, profiles) -> bool:
    ratios = [profile.effective_width / profile.effective_height for profile in profiles]
    if min(ratios, default=1.0) < 0.9 and max(ratios, default=1.0) > 1.25:
        return True
    if any(
        profile.recommended_layout
        in {"two_panels_fill", "panel_triptych", "weighted_two_images"}
        for profile in profiles
    ):
        return True
    area_ratios = [profile.effective_width * profile.effective_height for profile in profiles]
    if area_ratios and max(area_ratios) / max(1, min(area_ratios)) > 2.2:
        return True
    if all(len(profile.caption_panel_labels) >= 3 for profile in profiles):
        return True
    roles = {_semantic_role(figure.caption) for figure in figures}
    return "evidence" in roles and "application" in roles


def _semantic_role(caption):
    value = caption.casefold()
    if any(word in value for word in ("photophysical", "control experiment", "mechanistic")):
        return "evidence"
    if any(word in value for word in ("scope", "synthesis", "reaction", "functionalization")):
        return "application"
    return "other"


def _extract_callout(document, figure, title):
    keywords = {
        word.casefold()
        for word in re.findall(r"[A-Za-z]{5,}", f"{figure.caption} {title}")
        if word.casefold() not in {"figure", "reaction", "property"}
    }
    candidates = []
    for block in document.blocks:
        if (
            block.page_number != figure.page_number
            or not block.text
            or block.source_id == figure.caption_source_id
        ):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", block.text):
            sentence = sentence.strip()
            sentence = re.sub(r"^[A-Z][A-Za-z\s-]{8,80}(?=[A-Z][a-z])", "", sentence).strip()
            if 35 <= len(sentence) <= 220:
                score = sum(word in sentence.casefold() for word in keywords)
                if score:
                    candidates.append((score, sentence))
    if not candidates:
        return None
    sentence = max(candidates, key=lambda item: (item[0], -abs(len(item[1]) - 95)))[1]
    return _short_complete_extract(sentence)


def _short_complete_extract(sentence: str, limit: int = 125) -> str:
    """Keep a complete extractive thought; never truncate in the middle of a word."""
    sentence = re.sub(r"\s+", " ", sentence).strip()
    if len(sentence) <= limit:
        return sentence
    clauses = [part.strip() for part in re.split(r"(?<=[,;:])\s+", sentence) if part.strip()]
    selected: list[str] = []
    for clause in clauses:
        candidate = " ".join([*selected, clause])
        if len(candidate) > limit:
            break
        selected.append(clause)
    value = " ".join(selected).rstrip(" ,;:")
    if len(value) >= 45:
        return value + ("." if value[-1] not in ".!?" else "")
    for marker in (";", ","):
        prefix = sentence.split(marker, 1)[0].strip()
        if 45 <= len(prefix) <= limit:
            return prefix + "."
    return None


def _select_conclusion_hero(figures, profiles):
    ranked = sorted(
        zip(figures, profiles, strict=True),
        key=lambda pair: (
            pair[0].page_number,
            len(pair[1].panels),
            pair[1].content_density,
        ),
        reverse=True,
    )
    return ranked[0]


def _caption_title(figure, fallback):
    value = re.sub(r"^Figure\s+\d+\.\s*", "", figure.caption).strip()
    value = re.split(r"\s*\(B\)\s*", value, maxsplit=1)[0]
    value = re.sub(r"^\(A\)\s*", "", value).strip().rstrip(".")
    if " and " in value and len(value) > 52:
        value = value.split(" and ", 1)[0]
    return (value or fallback)[:58]


_GENERIC_ENGLISH_TITLES = {
    SlideType.BACKGROUND: "Scientific Context and Key Concepts",
    SlideType.RESEARCH_GAP: "Synthetic Challenge and Design Rationale",
    SlideType.REACTION_DESIGN: "Reaction Design and Key Transformation",
    SlideType.MECHANISM: "Mechanistic Proposal and Evidence",
    SlideType.APPLICATION: "Scope and Synthetic Applications",
    SlideType.LIMITATION: "Limitations and Open Questions",
    SlideType.CONCLUSION: "Key Findings and Outlook",
}


def _display_title(message, figures, language, slide_type):
    if language != "en":
        return _limit_title(message, 28)
    if len(figures) == 1:
        return _limit_title(_caption_title(figures[0], message), 54)
    return _limit_title(
        _GENERIC_ENGLISH_TITLES.get(slide_type, "Evidence-Grounded Analysis"), 54
    )


def _limit_title(value: str, maximum: int) -> str:
    """Keep banner titles single-line; shorten at a word boundary as a last resort."""
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= maximum:
        return normalized
    words = normalized.split()
    shortened = ""
    for word in words:
        candidate = f"{shortened} {word}".strip()
        if len(candidate) > maximum - 1:
            break
        shortened = candidate
    return f"{shortened.rstrip('.,;:')}…" if shortened else normalized[: maximum - 1] + "…"


def _is_quantitative_plot(caption: str) -> bool:
    value = caption.casefold()
    return any(
        term in value
        for term in (
            "hammett",
            "linear free-energy",
            "correlation",
            "regression",
            "kinetic plot",
            "rate plot",
        )
    )


def _sources(refs: list[EvidenceRef]) -> str:
    return (
        "\n".join(
            f"- {ref.label or ref.source_id}, PDF p.{ref.page_number} ({ref.source_id})"
            for ref in refs
        )
        or "- Title/organizational slide"
    )


def _has_inference(analysis, refs) -> bool:
    ids = {ref.source_id for ref in refs}
    claims = [
        *analysis.research_context,
        *analysis.research_gap,
        *analysis.hypothesis,
        *analysis.innovations,
        *analysis.key_results,
        *analysis.limitations,
    ]
    return any(
        claim.basis == ClaimBasis.INFERRED
        and (not claim.evidence or ids.intersection(ref.source_id for ref in claim.evidence))
        for claim in claims
    )
