from enum import StrEnum


class SessionStatus(StrEnum):
    CREATED = "created"
    DOCUMENT_UPLOADED = "document_uploaded"
    PARSING = "parsing"
    ANALYZING = "analyzing"
    NEEDS_REQUIREMENTS = "needs_requirements"
    PLANNING = "planning"
    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    COMPOSING = "composing"
    RENDERING = "rendering"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"
    CANCELLED = "cancelled"


class EvidenceKind(StrEnum):
    TEXT = "text"
    FIGURE = "figure"
    TABLE = "table"


class ClaimBasis(StrEnum):
    EXPLICIT = "explicit"
    SYNTHESIZED = "synthesized"
    INFERRED = "inferred"


class PresentationPurpose(StrEnum):
    GROUP_MEETING = "group_meeting"
    JOURNAL_CLUB = "journal_club"
    CONFERENCE = "conference"
    TEACHING = "teaching"
    LITERATURE_REVIEW = "literature_review"
    PROJECT_REPORT = "project_report"


class AudienceLevel(StrEnum):
    GENERAL = "general"
    CHEMISTRY = "chemistry"
    DOMAIN_EXPERT = "domain_expert"


class SlideType(StrEnum):
    TITLE = "title"
    BACKGROUND = "background"
    RESEARCH_GAP = "research_gap"
    REACTION_DESIGN = "reaction_design"
    OPTIMIZATION = "optimization"
    SUBSTRATE_SCOPE = "substrate_scope"
    MECHANISM = "mechanism"
    APPLICATION = "application"
    LIMITATION = "limitation"
    CONCLUSION = "conclusion"
