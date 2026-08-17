from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from chemresearch_agent.domain.enums import SessionStatus
from chemresearch_agent.domain.errors import InvalidTransitionError
from chemresearch_agent.domain.models import AgentSession, SessionEvent

TERMINAL_STATES = {
    SessionStatus.COMPLETED,
    SessionStatus.FAILED_FINAL,
    SessionStatus.CANCELLED,
}

ALLOWED_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.CREATED: {SessionStatus.DOCUMENT_UPLOADED, SessionStatus.CANCELLED},
    SessionStatus.DOCUMENT_UPLOADED: {SessionStatus.PARSING, SessionStatus.CANCELLED},
    SessionStatus.PARSING: {
        SessionStatus.ANALYZING,
        SessionStatus.FAILED_RETRYABLE,
        SessionStatus.FAILED_FINAL,
        SessionStatus.CANCELLED,
    },
    SessionStatus.ANALYZING: {
        SessionStatus.NEEDS_REQUIREMENTS,
        SessionStatus.FAILED_RETRYABLE,
        SessionStatus.FAILED_FINAL,
        SessionStatus.CANCELLED,
    },
    SessionStatus.NEEDS_REQUIREMENTS: {SessionStatus.PLANNING, SessionStatus.CANCELLED},
    SessionStatus.PLANNING: {
        SessionStatus.AWAITING_PLAN_APPROVAL,
        SessionStatus.FAILED_RETRYABLE,
        SessionStatus.FAILED_FINAL,
        SessionStatus.CANCELLED,
    },
    SessionStatus.AWAITING_PLAN_APPROVAL: {
        SessionStatus.PLANNING,
        SessionStatus.COMPOSING,
        SessionStatus.CANCELLED,
    },
    SessionStatus.COMPOSING: {
        SessionStatus.RENDERING,
        SessionStatus.FAILED_RETRYABLE,
        SessionStatus.FAILED_FINAL,
        SessionStatus.CANCELLED,
    },
    SessionStatus.RENDERING: {
        SessionStatus.VALIDATING,
        SessionStatus.FAILED_RETRYABLE,
        SessionStatus.FAILED_FINAL,
        SessionStatus.CANCELLED,
    },
    SessionStatus.VALIDATING: {
        SessionStatus.COMPLETED,
        SessionStatus.COMPOSING,
        SessionStatus.FAILED_RETRYABLE,
        SessionStatus.FAILED_FINAL,
        SessionStatus.CANCELLED,
    },
    SessionStatus.FAILED_RETRYABLE: {
        SessionStatus.PARSING,
        SessionStatus.ANALYZING,
        SessionStatus.PLANNING,
        SessionStatus.COMPOSING,
        SessionStatus.RENDERING,
        SessionStatus.VALIDATING,
        SessionStatus.FAILED_FINAL,
        SessionStatus.CANCELLED,
    },
    SessionStatus.COMPLETED: set(),
    SessionStatus.FAILED_FINAL: set(),
    SessionStatus.CANCELLED: set(),
}


@dataclass(frozen=True)
class SessionStateMachine:
    def transition(
        self,
        session: AgentSession,
        target: SessionStatus,
        *,
        reason: str | None = None,
    ) -> AgentSession:
        allowed = ALLOWED_TRANSITIONS[session.status]
        if target not in allowed:
            raise InvalidTransitionError(
                f"cannot transition session from {session.status.value} to {target.value}"
            )

        previous = session.status
        session.status = target
        session.updated_at = datetime.now(UTC)
        session.version += 1
        session.events.append(SessionEvent(from_status=previous, to_status=target, reason=reason))
        return session
