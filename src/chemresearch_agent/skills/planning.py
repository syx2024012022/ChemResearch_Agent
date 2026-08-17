from __future__ import annotations

from chemresearch_agent.domain.enums import SlideType
from chemresearch_agent.domain.models import (
    EvidenceRef,
    PaperAnalysis,
    PresentationRequirements,
    SlidePlan,
    SlidePlanItem,
)

from .templates import DEFAULT_TEMPLATE_BY_TYPE


class RuleBasedPresentationPlanningSkill:
    name = "presentation_planning"
    version = "0.1.0"

    def create_plan(
        self, analysis: PaperAnalysis, requirements: PresentationRequirements
    ) -> SlidePlan:
        target = requirements.target_slide_count
        candidates: list[tuple[SlideType, str, list[EvidenceRef]]] = [
            (SlideType.TITLE, analysis.metadata.title, []),
            (
                SlideType.BACKGROUND,
                _claim_text(analysis.research_context, "研究背景与核心概念"),
                _claim_refs(analysis.research_context),
            ),
        ]
        if _claim_refs(analysis.research_gap):
            candidates.append(
                (
                    SlideType.RESEARCH_GAP,
                    _claim_text(analysis.research_gap, "论文试图解决的关键问题"),
                    _claim_refs(analysis.research_gap),
                )
            )
        body: list[tuple[SlideType, str, list[EvidenceRef]]] = []
        for index, claim in enumerate(analysis.innovations):
            kind = SlideType.MECHANISM if index < 2 else SlideType.APPLICATION
            refs = _dedupe_refs(claim.evidence)
            if len(refs) >= 3:
                split = max(1, len(refs) // 2)
                body.append((kind, claim.text, refs[:split]))
                body.append(
                    (
                        SlideType.APPLICATION,
                        f"代表性反应与证据：{claim.text}",
                        refs[split:],
                    )
                )
            else:
                body.append((kind, claim.text, refs))
        for reaction in analysis.reactions:
            refs = reaction.evidence + (reaction.mechanism.evidence if reaction.mechanism else [])
            body.append((SlideType.REACTION_DESIGN, reaction.transformation, refs))
            if reaction.mechanism:
                body.append((SlideType.MECHANISM, reaction.mechanism.text, refs))
        body.sort(key=_first_evidence_page)
        candidates.extend(body)
        if analysis.limitations:
            candidates.append(
                (
                    SlideType.LIMITATION,
                    analysis.limitations[0].text,
                    analysis.limitations[0].evidence,
                )
            )
        candidates.append(
            (
                SlideType.CONCLUSION,
                _claim_text(
                    analysis.key_results,
                    _claim_text(analysis.innovations, "核心贡献与后续问题"),
                ),
                _claim_refs(analysis.key_results or analysis.innovations),
            )
        )
        if target is None:
            lower = requirements.min_slide_count or 6
            upper = requirements.max_slide_count or 18
            target = max(lower, min(upper, len(candidates)))
        if len(candidates) > target:
            candidates = candidates[: target - 1] + [candidates[-1]]
        seconds = (
            max(30, requirements.duration_minutes * 60 // len(candidates))
            if requirements.duration_minutes
            else None
        )
        slides = [
            SlidePlanItem(
                slide_id=f"slide-{index + 1:02d}",
                slide_type=kind,
                purpose="建立叙事并用论文证据支持本页结论",
                key_message=message[:180],
                source_refs=_dedupe_refs(refs)[:4],
                preferred_template=DEFAULT_TEMPLATE_BY_TYPE[kind],
                estimated_seconds=seconds,
            )
            for index, (kind, message, refs) in enumerate(candidates)
        ]
        return SlidePlan(
            title=analysis.metadata.title,
            slides=slides,
            rationale="按背景、问题、关键反应、机理、应用与结论形成递进叙事。",
        )


def _claim_text(claims, fallback: str) -> str:
    return claims[0].text if claims else fallback


def _claim_refs(claims) -> list[EvidenceRef]:
    return [ref for claim in claims for ref in claim.evidence]


def _dedupe_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    return list({ref.source_id: ref for ref in refs}.values())


def _first_evidence_page(candidate: tuple[SlideType, str, list[EvidenceRef]]) -> int:
    refs = candidate[2]
    return min((ref.page_number for ref in refs), default=10_000)
