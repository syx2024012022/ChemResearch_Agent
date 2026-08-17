from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from chemresearch_agent.domain.models import DocumentParseResult


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParserRunStatus(str):
    SUCCESS = "success"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    FAILED = "failed"


class ParserRunResult(EvaluationModel):
    parser_name: str
    parser_version: str | None = None
    status: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    elapsed_seconds: float = Field(default=0, ge=0)
    peak_memory_mb: float | None = Field(default=None, ge=0)
    deployment_points: float = Field(default=0, ge=0, le=15)
    document: DocumentParseResult | None = None
    markdown: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ScoreComponent(EvaluationModel):
    name: str
    earned: float
    possible: float
    details: str


class ParserScore(EvaluationModel):
    parser_name: str
    status: str
    score: float = Field(ge=0, le=100)
    components: list[ScoreComponent]
    gates: dict[str, bool]
    passes_required_gates: bool
    recommendation: str
