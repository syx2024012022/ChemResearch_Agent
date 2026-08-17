from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import (
    AudienceLevel,
    ClaimBasis,
    EvidenceKind,
    PresentationPurpose,
    SessionStatus,
    SlideType,
)


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BoundingBox(DomainModel):
    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def validate_coordinates(self) -> BoundingBox:
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("bounding box must have positive width and height")
        return self


class SourceBlock(DomainModel):
    source_id: str
    page_number: int = Field(ge=1)
    kind: EvidenceKind
    text: str | None = None
    bounding_box: BoundingBox | None = None
    asset_path: str | None = None
    label: str | None = None


class FigureRecord(DomainModel):
    figure_id: str
    label: str
    page_number: int = Field(ge=1)
    caption_source_id: str
    caption: str
    asset_path: str
    bounding_box: BoundingBox
    referenced_by_source_ids: list[str] = Field(default_factory=list)
    crop_method: str = "caption_anchored"
    confidence: float = Field(default=1.0, ge=0, le=1)


class FigurePanelRecord(DomainModel):
    panel_label: str
    asset_path: str
    crop_box: BoundingBox


class FigureVisualProfile(DomainModel):
    figure_id: str
    trimmed_asset_path: str
    original_width: int = Field(gt=0)
    original_height: int = Field(gt=0)
    effective_width: int = Field(gt=0)
    effective_height: int = Field(gt=0)
    content_density: float = Field(ge=0, le=1)
    caption_panel_labels: list[str] = Field(default_factory=list)
    detected_separators: list[int] = Field(default_factory=list)
    panels: list[FigurePanelRecord] = Field(default_factory=list)
    recommended_layout: str
    confidence: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)


class DocumentParseResult(DomainModel):
    document_id: UUID
    file_name: str
    file_hash: str
    page_count: int = Field(ge=1)
    blocks: list[SourceBlock] = Field(default_factory=list)
    figures: list[FigureRecord] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class EvidenceRef(DomainModel):
    source_id: str
    document_id: UUID
    page_number: int = Field(ge=1)
    kind: EvidenceKind = EvidenceKind.TEXT
    excerpt: str | None = None
    label: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)


class GroundedClaim(DomainModel):
    text: str
    basis: ClaimBasis
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def explicit_claim_requires_evidence(self) -> GroundedClaim:
        if self.basis == ClaimBasis.EXPLICIT and not self.evidence:
            raise ValueError("explicit claims require at least one evidence reference")
        return self


class ReactionAnalysis(DomainModel):
    transformation: str
    catalyst: str | None = None
    reagents: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    mechanism: GroundedClaim | None = None
    key_intermediates: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class PaperMetadata(DomainModel):
    title: str
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    year: int | None = Field(default=None, ge=1800, le=2200)
    doi: str | None = None


class PaperAnalysis(DomainModel):
    document_id: UUID
    metadata: PaperMetadata
    research_context: list[GroundedClaim] = Field(default_factory=list)
    research_gap: list[GroundedClaim] = Field(default_factory=list)
    hypothesis: list[GroundedClaim] = Field(default_factory=list)
    innovations: list[GroundedClaim] = Field(default_factory=list)
    reactions: list[ReactionAnalysis] = Field(default_factory=list)
    key_results: list[GroundedClaim] = Field(default_factory=list)
    limitations: list[GroundedClaim] = Field(default_factory=list)
    important_source_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PresentationRequirements(DomainModel):
    purpose: PresentationPurpose
    duration_minutes: int | None = Field(default=None, ge=3, le=120)
    audience_level: AudienceLevel = AudienceLevel.CHEMISTRY
    occasion: str = "课题组组会"
    language: str = "en"
    focus_topics: list[str] = Field(default_factory=list)
    target_slide_count: int | None = Field(default=None, ge=3, le=60)
    min_slide_count: int | None = Field(default=None, ge=3, le=60)
    max_slide_count: int | None = Field(default=None, ge=3, le=60)
    template_theme: str = "chem_group_standard"
    include_speaker_notes: bool = True
    special_instructions: str | None = None
    title_include_authors: bool = True
    title_include_publication: bool = True
    title_include_toc_graphic: bool = True
    require_visual_each_slide: bool = True
    prefer_visual_dominance: bool = True

    @model_validator(mode="after")
    def validate_slide_range(self) -> PresentationRequirements:
        if (self.min_slide_count is None) != (self.max_slide_count is None):
            raise ValueError("min_slide_count and max_slide_count must be provided together")
        if (
            self.min_slide_count is not None
            and self.max_slide_count is not None
            and self.min_slide_count > self.max_slide_count
        ):
            raise ValueError("min_slide_count cannot exceed max_slide_count")
        return self


class RequirementOption(DomainModel):
    value: str
    label: str
    description: str | None = None
    recommended: bool = False


class RequirementsQuestion(DomainModel):
    step: str
    prompt: str
    input_kind: str
    options: list[RequirementOption] = Field(default_factory=list)
    recommendation: str | None = None
    allows_custom: bool = True


class RequirementsInterview(DomainModel):
    current_step: str = "purpose"
    answers: dict[str, Any] = Field(default_factory=dict)
    focus_suggestions: list[str] = Field(default_factory=list)
    user_special_request: str | None = None
    expanded_special_instructions: str | None = None
    completed: bool = False


class SlidePlanItem(DomainModel):
    slide_id: str
    slide_type: SlideType
    purpose: str
    key_message: str
    source_refs: list[EvidenceRef] = Field(default_factory=list)
    preferred_template: str | None = None
    estimated_seconds: int | None = Field(default=None, gt=0, le=900)


class SlidePlan(DomainModel):
    title: str
    slides: list[SlidePlanItem] = Field(min_length=1)
    rationale: str

    @property
    def estimated_duration_seconds(self) -> int | None:
        values = [slide.estimated_seconds for slide in self.slides]
        return (
            sum(value for value in values if value is not None)
            if all(value is not None for value in values)
            else None
        )


class ContentBlock(DomainModel):
    slot: str
    text: str | None = None
    source_id: str | None = None
    asset_path: str | None = None
    figure_id: str | None = None
    panel_label: str | None = None
    crop_box: BoundingBox | None = None

    @model_validator(mode="after")
    def require_exactly_one_payload(self) -> ContentBlock:
        values = (self.text, self.source_id, self.asset_path)
        if sum(value is not None for value in values) != 1:
            raise ValueError("a content block requires exactly one payload")
        return self


class SlideContent(DomainModel):
    slide_id: str
    origin_plan_slide_id: str | None = None
    title: str
    template_id: str
    blocks: list[ContentBlock] = Field(default_factory=list)
    citations: list[EvidenceRef] = Field(default_factory=list)
    speaker_notes: str | None = None
    layout_decision: LayoutDecision | None = None
    composition_warnings: list[str] = Field(default_factory=list)


class LayoutDecision(DomainModel):
    layout: str
    reason: str
    figure_ids: list[str] = Field(default_factory=list)
    panel_labels: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    auto_split: bool = False


class ValidationIssue(DomainModel):
    code: str
    message: str
    slide_id: str | None = None
    severity: str = "error"


class ValidationReport(DomainModel):
    passed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PresentationArtifact(DomainModel):
    artifact_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    pptx_path: str
    preview_paths: list[str] = Field(default_factory=list)
    layout_paths: list[str] = Field(default_factory=list)
    montage_path: str | None = None
    render_log: list[str] = Field(default_factory=list)
    renderer_version: str
    input_hash: str
    slide_count: int = Field(ge=1)
    validation: ValidationReport | None = None


class TemplateSlotSpec(DomainModel):
    name: str
    kind: str
    required: bool = True
    max_characters: int | None = Field(default=None, gt=0)
    max_items: int | None = Field(default=None, gt=0)


class TemplateSpec(DomainModel):
    template_id: str
    slide_type: SlideType
    layout: str
    slots: list[TemplateSlotSpec] = Field(min_length=1)
    fallback_template_id: str | None = None
    renderer_version: str

    @model_validator(mode="after")
    def slot_names_must_be_unique(self) -> TemplateSpec:
        names = [slot.name for slot in self.slots]
        if len(names) != len(set(names)):
            raise ValueError("template slot names must be unique")
        return self


class SessionEvent(DomainModel):
    from_status: SessionStatus | None
    to_status: SessionStatus
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str | None = None


class AgentSession(DomainModel):
    session_id: UUID = Field(default_factory=uuid4)
    status: SessionStatus = SessionStatus.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    document_id: UUID | None = None
    requirements: PresentationRequirements | None = None
    requirements_interview: RequirementsInterview | None = None
    paper_analysis: PaperAnalysis | None = None
    slide_plan: SlidePlan | None = None
    slide_contents: list[SlideContent] = Field(default_factory=list)
    validation_report: ValidationReport | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    events: list[SessionEvent] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    version: int = Field(default=0, ge=0)
