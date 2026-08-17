from __future__ import annotations

from pathlib import Path
from uuid import UUID

from chemresearch_agent.domain.errors import AnalysisUnavailableError, InvalidTransitionError
from chemresearch_agent.domain.models import AgentSession, PresentationArtifact

from .orchestrator import AgentOrchestrator
from .ports import (
    ArtifactRepository,
    DocumentRepository,
    PresentationComposerSkill,
    PresentationPlanningSkill,
    PresentationRenderer,
    PresentationValidator,
)


class PresentationPlanningService:
    def __init__(self, orchestrator: AgentOrchestrator, skill: PresentationPlanningSkill) -> None:
        self._orchestrator = orchestrator
        self._skill = skill

    def create_plan(self, session_id: UUID) -> AgentSession:
        session = self._orchestrator.get_session(session_id)
        if not session.paper_analysis or not session.requirements:
            raise InvalidTransitionError(
                "analysis and user requirements are required before planning"
            )
        plan = self._skill.create_plan(session.paper_analysis, session.requirements)
        return self._orchestrator.record_plan(session_id, plan)


class PresentationGenerationService:
    def __init__(
        self,
        orchestrator: AgentOrchestrator,
        documents: DocumentRepository,
        artifacts: ArtifactRepository,
        composer: PresentationComposerSkill,
        renderer: PresentationRenderer | None,
        validator: PresentationValidator,
        output_root: Path,
    ) -> None:
        self._orchestrator = orchestrator
        self._documents = documents
        self._artifacts = artifacts
        self._composer = composer
        self._renderer = renderer
        self._validator = validator
        self._output_root = output_root

    def generate(self, session_id: UUID) -> tuple[AgentSession, PresentationArtifact]:
        if self._renderer is None:
            raise AnalysisUnavailableError("presentation renderer is not configured")
        session = self._orchestrator.get_session(session_id)
        if not all(
            [session.slide_plan, session.paper_analysis, session.requirements, session.document_id]
        ):
            raise InvalidTransitionError(
                "approved plan, analysis, requirements and document are required"
            )
        document = self._documents.get(session.document_id)
        contents = self._composer.compose(
            session.slide_plan,
            session.paper_analysis,
            document,
            session.requirements,
            self._output_root / str(session_id) / "composition-assets",
        )
        self._orchestrator.record_composition(session_id, contents)
        artifact = self._renderer.render(session_id, contents, self._output_root)
        self._orchestrator.finish_rendering(session_id, artifact.artifact_id)
        report = self._validator.validate(
            session.slide_plan, contents, artifact, session.requirements
        )
        artifact.validation = report
        artifact = self._artifacts.save(artifact)
        updated = self._orchestrator.record_validation(session_id, report)
        return updated, artifact
