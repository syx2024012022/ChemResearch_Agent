from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from chemresearch_agent.domain.models import (
    AgentSession,
    DocumentParseResult,
    PaperAnalysis,
    PresentationArtifact,
    PresentationRequirements,
    SlideContent,
    SlidePlan,
    TemplateSpec,
    ValidationReport,
)


class SessionRepository(Protocol):
    def create(self, session: AgentSession) -> AgentSession: ...

    def get(self, session_id: UUID) -> AgentSession: ...

    def save(self, session: AgentSession, *, expected_version: int) -> AgentSession: ...


class FileStore(Protocol):
    def save_upload(self, file_name: str, content: bytes) -> tuple[UUID, Path, str]: ...


class DocumentRepository(Protocol):
    def save(self, document: DocumentParseResult) -> DocumentParseResult: ...

    def get(self, document_id: UUID) -> DocumentParseResult: ...


class PdfParser(Protocol):
    def parse(self, document_id: UUID, path: Path) -> DocumentParseResult: ...


class LiteratureSkill(Protocol):
    def analyze(self, document: DocumentParseResult) -> PaperAnalysis: ...


class PresentationPlanningSkill(Protocol):
    def create_plan(
        self,
        analysis: PaperAnalysis,
        requirements: PresentationRequirements,
    ) -> SlidePlan: ...


class PresentationComposerSkill(Protocol):
    def compose(
        self,
        plan: SlidePlan,
        analysis: PaperAnalysis,
        document: DocumentParseResult,
        requirements: PresentationRequirements,
        composition_asset_dir: Path | None = None,
    ) -> list[SlideContent]: ...


class TemplateRegistry(Protocol):
    def get(self, template_id: str) -> TemplateSpec: ...

    def all(self) -> list[TemplateSpec]: ...


class PresentationRenderer(Protocol):
    def render(
        self,
        session_id: UUID,
        contents: list[SlideContent],
        output_root: Path,
    ) -> PresentationArtifact: ...


class PresentationValidator(Protocol):
    def validate(
        self,
        plan: SlidePlan,
        contents: list[SlideContent],
        artifact: PresentationArtifact,
        requirements: PresentationRequirements | None = None,
    ) -> ValidationReport: ...


class ArtifactRepository(Protocol):
    def save(self, artifact: PresentationArtifact) -> PresentationArtifact: ...

    def get(self, artifact_id: UUID) -> PresentationArtifact: ...

    def get_for_session(self, session_id: UUID) -> PresentationArtifact: ...
