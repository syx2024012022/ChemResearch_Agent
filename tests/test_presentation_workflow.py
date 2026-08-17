from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from chemresearch_agent.application.orchestrator import AgentOrchestrator
from chemresearch_agent.application.presentation_workflow import (
    PresentationGenerationService,
    PresentationPlanningService,
)
from chemresearch_agent.domain.enums import (
    ClaimBasis,
    EvidenceKind,
    PresentationPurpose,
    SessionStatus,
)
from chemresearch_agent.domain.errors import InvalidTransitionError
from chemresearch_agent.domain.models import (
    DocumentParseResult,
    EvidenceRef,
    GroundedClaim,
    PaperAnalysis,
    PaperMetadata,
    PresentationArtifact,
    PresentationRequirements,
    SourceBlock,
)
from chemresearch_agent.infrastructure.artifact_repository import JsonArtifactRepository
from chemresearch_agent.infrastructure.document_repository import JsonDocumentRepository
from chemresearch_agent.infrastructure.persistence import JsonSessionRepository
from chemresearch_agent.skills.composer import RuleBasedPresentationComposerSkill
from chemresearch_agent.skills.planning import RuleBasedPresentationPlanningSkill
from chemresearch_agent.skills.validation import DeterministicPresentationValidator


class FakeRenderer:
    def render(self, session_id, contents, output_root):
        output_root.mkdir(parents=True, exist_ok=True)
        pptx = output_root / "test.pptx"
        pptx.write_bytes(b"PK test pptx")
        previews = []
        for index, _ in enumerate(contents):
            preview = output_root / f"slide-{index + 1:02d}.png"
            preview.write_bytes(b"png")
            previews.append(str(preview))
        return PresentationArtifact(
            session_id=session_id,
            pptx_path=str(pptx),
            preview_paths=previews,
            renderer_version="fake",
            input_hash="abc",
            slide_count=len(contents),
        )


def fixture_document() -> DocumentParseResult:
    document_id = uuid4()
    return DocumentParseResult(
        document_id=document_id,
        file_name="paper.pdf",
        file_hash="abc",
        page_count=1,
        blocks=[
            SourceBlock(
                source_id="p1-b1",
                page_number=1,
                kind=EvidenceKind.TEXT,
                text="An electron-rich intermediate enables SET.",
            )
        ],
    )


def fixture_analysis(document: DocumentParseResult) -> PaperAnalysis:
    ref = EvidenceRef(
        source_id="p1-b1",
        document_id=document.document_id,
        page_number=1,
        excerpt="An electron-rich intermediate enables SET.",
    )
    return PaperAnalysis(
        document_id=document.document_id,
        metadata=PaperMetadata(title="Test chemistry"),
        research_context=[
            GroundedClaim(text="研究背景", basis=ClaimBasis.EXPLICIT, evidence=[ref])
        ],
        research_gap=[GroundedClaim(text="关键问题", basis=ClaimBasis.EXPLICIT, evidence=[ref])],
        innovations=[GroundedClaim(text="核心贡献", basis=ClaimBasis.EXPLICIT, evidence=[ref])],
    )


class PresentationWorkflowTests(unittest.TestCase):
    def test_page_range_drives_plan_without_time_estimates(self) -> None:
        document = fixture_document()
        analysis = fixture_analysis(document)
        plan = RuleBasedPresentationPlanningSkill().create_plan(
            analysis,
            PresentationRequirements(
                purpose=PresentationPurpose.GROUP_MEETING,
                min_slide_count=3,
                max_slide_count=6,
            ),
        )
        self.assertGreaterEqual(len(plan.slides), 3)
        self.assertLessEqual(len(plan.slides), 6)
        self.assertIsNone(plan.estimated_duration_seconds)

    def test_complete_workflow_requires_approval_and_finishes_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            orchestrator = AgentOrchestrator(JsonSessionRepository(root / "sessions"))
            documents = JsonDocumentRepository(root / "documents")
            artifacts = JsonArtifactRepository(root / "artifacts")
            document = documents.save(fixture_document())
            session = orchestrator.create_session()
            orchestrator.attach_document(session.session_id, document.document_id)
            orchestrator.start_parsing(session.session_id)
            orchestrator.finish_parsing(session.session_id)
            orchestrator.record_analysis(session.session_id, fixture_analysis(document))
            orchestrator.submit_requirements(
                session.session_id,
                PresentationRequirements(
                    purpose=PresentationPurpose.GROUP_MEETING,
                    duration_minutes=10,
                    target_slide_count=5,
                    title_include_toc_graphic=False,
                    require_visual_each_slide=False,
                ),
            )
            planned = PresentationPlanningService(
                orchestrator, RuleBasedPresentationPlanningSkill()
            ).create_plan(session.session_id)
            self.assertEqual(planned.status, SessionStatus.AWAITING_PLAN_APPROVAL)
            service = PresentationGenerationService(
                orchestrator,
                documents,
                artifacts,
                RuleBasedPresentationComposerSkill(),
                FakeRenderer(),
                DeterministicPresentationValidator(),
                root / "output",
            )
            with self.assertRaises(InvalidTransitionError):
                service.generate(session.session_id)
            orchestrator.approve_plan(session.session_id)
            completed, artifact = service.generate(session.session_id)
            self.assertEqual(completed.status, SessionStatus.COMPLETED)
            self.assertTrue(artifact.validation.passed)
            self.assertTrue(completed.slide_contents)

    def test_plan_can_return_to_planning_for_user_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            orchestrator = AgentOrchestrator(JsonSessionRepository(Path(directory)))
            session = orchestrator.create_session()
            document_id = uuid4()
            orchestrator.attach_document(session.session_id, document_id)
            orchestrator.start_parsing(session.session_id)
            orchestrator.finish_parsing(session.session_id)
            analysis = PaperAnalysis(document_id=document_id, metadata=PaperMetadata(title="Test"))
            orchestrator.record_analysis(session.session_id, analysis)
            orchestrator.submit_requirements(
                session.session_id,
                PresentationRequirements(
                    purpose=PresentationPurpose.GROUP_MEETING,
                    duration_minutes=10,
                    title_include_toc_graphic=False,
                    require_visual_each_slide=False,
                ),
            )
            plan = RuleBasedPresentationPlanningSkill().create_plan(
                analysis,
                orchestrator.get_session(session.session_id).requirements,
            )
            orchestrator.record_plan(session.session_id, plan)
            revised = orchestrator.request_plan_revision(session.session_id, "增加机理页")
            self.assertEqual(revised.status, SessionStatus.PLANNING)
            self.assertEqual(revised.events[-1].reason, "增加机理页")


if __name__ == "__main__":
    unittest.main()
