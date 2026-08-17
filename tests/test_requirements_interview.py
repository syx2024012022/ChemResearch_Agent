from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

from chemresearch_agent.application.orchestrator import AgentOrchestrator
from chemresearch_agent.application.requirements_interview import GuidedRequirementsService
from chemresearch_agent.domain.enums import ClaimBasis, SessionStatus
from chemresearch_agent.domain.models import GroundedClaim, PaperAnalysis, PaperMetadata
from chemresearch_agent.infrastructure.persistence import JsonSessionRepository


def ready_session(orchestrator: AgentOrchestrator):
    session = orchestrator.create_session()
    document_id = uuid4()
    orchestrator.attach_document(session.session_id, document_id)
    orchestrator.start_parsing(session.session_id)
    orchestrator.finish_parsing(session.session_id)
    analysis = PaperAnalysis(
        document_id=document_id,
        metadata=PaperMetadata(title="N-BPA"),
        innovations=[GroundedClaim(text="N-BPA 作为强电子供体", basis=ClaimBasis.INFERRED)],
        key_results=[GroundedClaim(text="兼具自由基和极性反应模式", basis=ClaimBasis.INFERRED)],
    )
    return orchestrator.record_analysis(session.session_id, analysis)


def test_guided_interview_expands_request_and_submits_requirements():
    with tempfile.TemporaryDirectory() as directory:
        orchestrator = AgentOrchestrator(JsonSessionRepository(Path(directory)))
        session = ready_session(orchestrator)
        service = GuidedRequirementsService(orchestrator)
        _, question = service.start(session.session_id)
        assert question.step == "purpose"
        answers = [
            ("purpose", "group_meeting"),
            ("occasion", "课题组内部，有机化学研究生和老师"),
            ("language", "zh-CN"),
            ("focus_topics", ["N-BPA 作为强电子供体", "兼具自由基和极性反应模式"]),
            ("include_speaker_notes", True),
            ("special_instructions", "图多字少，排版较满"),
            ("special_confirmation", True),
            ("slide_count_range", "about_12"),
        ]
        current = None
        for step, value in answers:
            current, question = service.answer(session.session_id, step, value)
        assert current.status == SessionStatus.PLANNING
        assert current.requirements.min_slide_count == 11
        assert current.requirements.max_slide_count == 13
        assert "用户原始要求" in current.requirements.special_instructions
        assert current.requirements_interview.completed
        assert question is None


def test_rejected_expansion_returns_to_special_request():
    with tempfile.TemporaryDirectory() as directory:
        orchestrator = AgentOrchestrator(JsonSessionRepository(Path(directory)))
        session = ready_session(orchestrator)
        service = GuidedRequirementsService(orchestrator)
        service.start(session.session_id)
        for step, value in [
            ("purpose", "group_meeting"),
            ("occasion", "组会"),
            ("language", "zh-CN"),
            ("focus_topics", ["N-BPA"]),
            ("include_speaker_notes", True),
            ("special_instructions", "简洁"),
        ]:
            service.answer(session.session_id, step, value)
        _, question = service.answer(session.session_id, "special_confirmation", False)
        assert question.step == "special_instructions"
