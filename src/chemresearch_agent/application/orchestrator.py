from __future__ import annotations

from uuid import UUID

from chemresearch_agent.domain.enums import SessionStatus
from chemresearch_agent.domain.errors import InvalidTransitionError
from chemresearch_agent.domain.models import (
    AgentSession,
    PaperAnalysis,
    PresentationRequirements,
    RequirementsInterview,
    SlideContent,
    SlidePlan,
    ValidationReport,
)

from .ports import SessionRepository
from .state_machine import SessionStateMachine


class AgentOrchestrator:
    """Coordinates workflow gates; specialist work remains behind skill ports."""

    def __init__(self, sessions: SessionRepository) -> None:
        self._sessions = sessions
        self._states = SessionStateMachine()

    def create_session(self) -> AgentSession:
        return self._sessions.create(AgentSession())

    def get_session(self, session_id: UUID) -> AgentSession:
        return self._sessions.get(session_id)

    def attach_document(self, session_id: UUID, document_id: UUID) -> AgentSession:
        session = self._sessions.get(session_id)
        expected_version = session.version
        if session.document_id is not None and session.document_id != document_id:
            raise InvalidTransitionError("a document is already attached to this session")
        session.document_id = document_id
        self._states.transition(session, SessionStatus.DOCUMENT_UPLOADED)
        return self._sessions.save(session, expected_version=expected_version)

    def start_parsing(self, session_id: UUID) -> AgentSession:
        session = self._sessions.get(session_id)
        expected_version = session.version
        self._states.transition(session, SessionStatus.PARSING)
        return self._sessions.save(session, expected_version=expected_version)

    def finish_parsing(self, session_id: UUID) -> AgentSession:
        session = self._sessions.get(session_id)
        expected_version = session.version
        self._states.transition(session, SessionStatus.ANALYZING)
        return self._sessions.save(session, expected_version=expected_version)

    def record_analysis(self, session_id: UUID, analysis: PaperAnalysis) -> AgentSession:
        session = self._sessions.get(session_id)
        expected_version = session.version
        if session.status != SessionStatus.ANALYZING:
            raise InvalidTransitionError("analysis can only be recorded while analyzing")
        if session.document_id != analysis.document_id:
            raise InvalidTransitionError("analysis belongs to a different document")
        session.paper_analysis = analysis
        self._states.transition(session, SessionStatus.NEEDS_REQUIREMENTS)
        return self._sessions.save(session, expected_version=expected_version)

    def record_retryable_failure(
        self, session_id: UUID, error: Exception, *, reason: str = "workflow step failed"
    ) -> AgentSession:
        session = self._sessions.get(session_id)
        expected_version = session.version
        session.error = {"type": type(error).__name__, "message": str(error)}
        self._states.transition(
            session,
            SessionStatus.FAILED_RETRYABLE,
            reason=reason,
        )
        return self._sessions.save(session, expected_version=expected_version)

    def submit_requirements(
        self,
        session_id: UUID,
        requirements: PresentationRequirements,
    ) -> AgentSession:
        session = self._sessions.get(session_id)
        expected_version = session.version
        if session.status != SessionStatus.NEEDS_REQUIREMENTS:
            raise InvalidTransitionError("requirements are accepted only after paper analysis")
        session.requirements = requirements
        self._states.transition(session, SessionStatus.PLANNING)
        return self._sessions.save(session, expected_version=expected_version)

    def record_requirements_interview(
        self, session_id: UUID, interview: RequirementsInterview
    ) -> AgentSession:
        session = self._sessions.get(session_id)
        expected_version = session.version
        if session.status != SessionStatus.NEEDS_REQUIREMENTS:
            raise InvalidTransitionError("requirements interview is available only after analysis")
        session.requirements_interview = interview
        session.version += 1
        return self._sessions.save(session, expected_version=expected_version)

    def record_plan(self, session_id: UUID, plan: SlidePlan) -> AgentSession:
        session = self._sessions.get(session_id)
        expected_version = session.version
        if session.status != SessionStatus.PLANNING:
            raise InvalidTransitionError("a plan can only be recorded while planning")
        session.slide_plan = plan
        self._states.transition(session, SessionStatus.AWAITING_PLAN_APPROVAL)
        return self._sessions.save(session, expected_version=expected_version)

    def approve_plan(self, session_id: UUID) -> AgentSession:
        session = self._sessions.get(session_id)
        expected_version = session.version
        if session.slide_plan is None:
            raise InvalidTransitionError("cannot approve a missing slide plan")
        self._states.transition(session, SessionStatus.COMPOSING, reason="user approved plan")
        return self._sessions.save(session, expected_version=expected_version)

    def request_plan_revision(self, session_id: UUID, reason: str) -> AgentSession:
        session = self._sessions.get(session_id)
        expected_version = session.version
        if session.status != SessionStatus.AWAITING_PLAN_APPROVAL:
            raise InvalidTransitionError("plan revision requires a plan awaiting approval")
        self._states.transition(session, SessionStatus.PLANNING, reason=reason)
        return self._sessions.save(session, expected_version=expected_version)

    def record_composition(self, session_id: UUID, contents: list[SlideContent]) -> AgentSession:
        session = self._sessions.get(session_id)
        expected_version = session.version
        if session.status != SessionStatus.COMPOSING:
            raise InvalidTransitionError("content can only be recorded while composing")
        session.slide_contents = contents
        self._states.transition(session, SessionStatus.RENDERING)
        return self._sessions.save(session, expected_version=expected_version)

    def finish_rendering(self, session_id: UUID, artifact_id: UUID) -> AgentSession:
        session = self._sessions.get(session_id)
        expected_version = session.version
        if session.status != SessionStatus.RENDERING:
            raise InvalidTransitionError("rendering can only finish while rendering")
        session.artifact_ids.append(str(artifact_id))
        self._states.transition(session, SessionStatus.VALIDATING)
        return self._sessions.save(session, expected_version=expected_version)

    def record_validation(self, session_id: UUID, report: ValidationReport) -> AgentSession:
        session = self._sessions.get(session_id)
        expected_version = session.version
        if session.status != SessionStatus.VALIDATING:
            raise InvalidTransitionError("validation can only finish while validating")
        session.validation_report = report
        target = SessionStatus.COMPLETED if report.passed else SessionStatus.COMPOSING
        self._states.transition(session, target, reason="presentation validation finished")
        return self._sessions.save(session, expected_version=expected_version)

    def prepare_presentation_retry(self, session_id: UUID) -> AgentSession:
        session = self._sessions.get(session_id)
        expected_version = session.version
        if session.status != SessionStatus.FAILED_RETRYABLE:
            raise InvalidTransitionError("presentation retry requires a retryable failure")
        if not all(
            [session.slide_plan, session.paper_analysis, session.requirements, session.document_id]
        ):
            raise InvalidTransitionError("presentation retry is missing required session data")
        session.error = None
        self._states.transition(
            session, SessionStatus.COMPOSING, reason="user retried presentation generation"
        )
        return self._sessions.save(session, expected_version=expected_version)
