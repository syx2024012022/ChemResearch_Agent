from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from chemresearch_agent.application.literature_analysis import LiteratureAnalysisService
from chemresearch_agent.application.orchestrator import AgentOrchestrator
from chemresearch_agent.domain.enums import ClaimBasis, EvidenceKind, SessionStatus
from chemresearch_agent.domain.errors import EvidenceGroundingError
from chemresearch_agent.domain.models import DocumentParseResult, PaperMetadata, SourceBlock
from chemresearch_agent.infrastructure.document_repository import JsonDocumentRepository
from chemresearch_agent.infrastructure.persistence import JsonSessionRepository
from chemresearch_agent.skills.literature import (
    ClaimDraft,
    LiteratureAnalysisDraft,
    LiteratureAnalysisSkill,
    ReactionDraft,
)
from chemresearch_agent.tools.llm import LlmUsage, StructuredLlmResult


class FakeStructuredClient:
    def __init__(self, draft: LiteratureAnalysisDraft) -> None:
        self.draft = draft
        self.last_prompt = ""

    def generate(self, **kwargs):
        self.last_prompt = kwargs["user_prompt"]
        return StructuredLlmResult(
            value=self.draft,
            model="fake-structured-model",
            usage=LlmUsage(input_tokens=100, output_tokens=20),
        )


def sample_document() -> DocumentParseResult:
    return DocumentParseResult(
        document_id=uuid4(),
        file_name="paper.pdf",
        file_hash="abc",
        page_count=2,
        blocks=[
            SourceBlock(
                source_id="p1-b1",
                page_number=1,
                kind=EvidenceKind.TEXT,
                text="N-boryl pyridyl anions act as strong electron donors.",
                label="Introduction",
            ),
            SourceBlock(
                source_id="p2-b1",
                page_number=2,
                kind=EvidenceKind.TEXT,
                text="The radical mechanism was supported by control experiments.",
                label="Mechanism",
            ),
        ],
    )


def valid_draft() -> LiteratureAnalysisDraft:
    return LiteratureAnalysisDraft(
        metadata=PaperMetadata(title="N-Boryl Pyridyl Anion Chemistry"),
        research_context=[
            ClaimDraft(
                text="N-BPA 可作为强电子给体。",
                basis=ClaimBasis.EXPLICIT,
                source_ids=["p1-b1"],
            )
        ],
        reactions=[
            ReactionDraft(
                transformation="single-electron transfer",
                mechanism=ClaimDraft(
                    text="控制实验支持自由基机理。",
                    basis=ClaimBasis.EXPLICIT,
                    source_ids=["p2-b1"],
                ),
                source_ids=["p1-b1", "p2-b1"],
            )
        ],
        important_source_ids=["p1-b1", "p2-b1"],
    )


class LiteratureAnalysisTests(unittest.TestCase):
    def test_skill_resolves_source_ids_into_evidence(self) -> None:
        document = sample_document()
        client = FakeStructuredClient(valid_draft())
        analysis = LiteratureAnalysisSkill(client).analyze(document)
        self.assertEqual(analysis.document_id, document.document_id)
        self.assertEqual(analysis.research_context[0].evidence[0].page_number, 1)
        self.assertEqual(analysis.reactions[0].mechanism.evidence[0].source_id, "p2-b1")
        self.assertIn("p1-b1 | page 1", client.last_prompt)

    def test_skill_rejects_hallucinated_source_id(self) -> None:
        document = sample_document()
        draft = valid_draft().model_copy(update={"important_source_ids": ["invented"]})
        with self.assertRaises(EvidenceGroundingError):
            LiteratureAnalysisSkill(FakeStructuredClient(draft)).analyze(document)

    def test_service_records_analysis_and_opens_user_requirements_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            orchestrator = AgentOrchestrator(JsonSessionRepository(root / "sessions"))
            documents = JsonDocumentRepository(root / "documents")
            document = documents.save(sample_document())
            session = orchestrator.create_session()
            orchestrator.attach_document(session.session_id, document.document_id)
            orchestrator.start_parsing(session.session_id)
            orchestrator.finish_parsing(session.session_id)
            service = LiteratureAnalysisService(
                orchestrator,
                documents,
                LiteratureAnalysisSkill(FakeStructuredClient(valid_draft())),
            )
            result = service.analyze(session.session_id)
            self.assertEqual(result.session.status, SessionStatus.NEEDS_REQUIREMENTS)
            self.assertIsNotNone(result.session.paper_analysis)


if __name__ == "__main__":
    unittest.main()
