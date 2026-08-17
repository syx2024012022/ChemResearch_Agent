from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from chemresearch_agent.domain.errors import InvalidTransitionError
from chemresearch_agent.domain.models import AgentSession, PaperAnalysis

from .orchestrator import AgentOrchestrator
from .ports import DocumentRepository, LiteratureSkill


@dataclass(frozen=True)
class LiteratureAnalysisResult:
    session: AgentSession
    analysis: PaperAnalysis


class LiteratureAnalysisService:
    def __init__(
        self,
        orchestrator: AgentOrchestrator,
        documents: DocumentRepository,
        skill: LiteratureSkill,
    ) -> None:
        self._orchestrator = orchestrator
        self._documents = documents
        self._skill = skill

    def analyze(self, session_id: UUID) -> LiteratureAnalysisResult:
        session = self._orchestrator.get_session(session_id)
        if session.document_id is None:
            raise InvalidTransitionError("session has no parsed document")
        document = self._documents.get(session.document_id)
        analysis = self._skill.analyze(document)
        updated = self._orchestrator.record_analysis(session_id, analysis)
        return LiteratureAnalysisResult(session=updated, analysis=analysis)
