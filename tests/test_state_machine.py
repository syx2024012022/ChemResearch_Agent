import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from chemresearch_agent.application.orchestrator import AgentOrchestrator
from chemresearch_agent.application.state_machine import SessionStateMachine
from chemresearch_agent.domain.enums import SessionStatus
from chemresearch_agent.domain.errors import ConcurrentUpdateError, InvalidTransitionError
from chemresearch_agent.domain.models import AgentSession
from chemresearch_agent.infrastructure.persistence import JsonSessionRepository


class StateMachineTests(unittest.TestCase):
    def test_valid_transition_is_recorded(self) -> None:
        session = AgentSession()
        result = SessionStateMachine().transition(session, SessionStatus.DOCUMENT_UPLOADED)
        self.assertEqual(result.status, SessionStatus.DOCUMENT_UPLOADED)
        self.assertEqual(result.version, 1)
        self.assertEqual(result.events[-1].from_status, SessionStatus.CREATED)

    def test_invalid_transition_is_rejected(self) -> None:
        with self.assertRaises(InvalidTransitionError):
            SessionStateMachine().transition(AgentSession(), SessionStatus.COMPLETED)

    def test_orchestrator_persists_document_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonSessionRepository(Path(directory))
            orchestrator = AgentOrchestrator(repository)
            session = orchestrator.create_session()
            document_id = uuid4()
            updated = orchestrator.attach_document(session.session_id, document_id)
            restored = orchestrator.get_session(session.session_id)
            self.assertEqual(updated.status, SessionStatus.DOCUMENT_UPLOADED)
            self.assertEqual(restored.document_id, document_id)
            self.assertEqual(restored.version, 1)

    def test_repository_rejects_stale_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonSessionRepository(Path(directory))
            session = repository.create(AgentSession())
            stale = repository.get(session.session_id)
            fresh = repository.get(session.session_id)
            SessionStateMachine().transition(fresh, SessionStatus.DOCUMENT_UPLOADED)
            repository.save(fresh, expected_version=0)
            SessionStateMachine().transition(stale, SessionStatus.DOCUMENT_UPLOADED)
            with self.assertRaises(ConcurrentUpdateError):
                repository.save(stale, expected_version=0)


if __name__ == "__main__":
    unittest.main()
