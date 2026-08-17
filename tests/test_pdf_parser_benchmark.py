from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from chemresearch_agent.domain.enums import EvidenceKind
from chemresearch_agent.domain.models import BoundingBox, DocumentParseResult, SourceBlock
from chemresearch_agent.evaluation.pdf_parsers.base import PdfParserAdapter
from chemresearch_agent.evaluation.pdf_parsers.benchmark import ParserBenchmark
from chemresearch_agent.evaluation.pdf_parsers.grobid_adapter import GrobidAdapter
from chemresearch_agent.evaluation.pdf_parsers.mineru_adapter import MinerUAdapter
from chemresearch_agent.evaluation.pdf_parsers.models import ParserRunResult, ParserRunStatus


class SuccessfulFakeAdapter(PdfParserAdapter):
    name = "fake"
    deployment_points = 15

    def parse(self, document_id, pdf_path, work_dir):
        blocks = [
            SourceBlock(
                source_id="section",
                page_number=1,
                kind=EvidenceKind.TEXT,
                text="1. INTRODUCTION 2. METHODS",
                bounding_box=BoundingBox(x0=0, y0=0, x1=10, y1=10),
            ),
            SourceBlock(
                source_id="figure",
                page_number=1,
                kind=EvidenceKind.TEXT,
                text="Figure 1. Caption",
                label="Figure 1",
                bounding_box=BoundingBox(x0=0, y0=20, x1=10, y1=30),
            ),
        ]
        artifact = work_dir / "raw.txt"
        artifact.write_text("raw", encoding="utf-8")
        return ParserRunResult(
            parser_name=self.name,
            status=ParserRunStatus.SUCCESS,
            document=DocumentParseResult(
                document_id=document_id,
                file_name=pdf_path.name,
                file_hash="hash",
                page_count=1,
                blocks=blocks,
                metadata={"title": "Test", "doi": "10.1/test", "authors": "A"},
            ),
            markdown="Test anchor (1)",
            artifacts={"raw": str(artifact)},
        )


class FailingFakeAdapter(PdfParserAdapter):
    name = "failing"

    def parse(self, document_id, pdf_path, work_dir):
        (work_dir / "partial.txt").write_text("partial", encoding="utf-8")
        raise RuntimeError("expected failure")


class PdfParserBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pdf = self.root / "test.pdf"
        self.pdf.write_bytes(b"%PDF-test")
        self.gold = self.root / "gold.json"
        self.gold.write_text(
            json.dumps(
                {
                    "title": "Test",
                    "authors": ["A"],
                    "doi": "10.1/test",
                    "page_count": 1,
                    "reference_count": 1,
                    "sections": ["1. INTRODUCTION", "2. METHODS"],
                    "text_anchors": ["Test anchor"],
                    "figures": {"Figure 1": 1},
                    "visual_review_passed": ["fake"],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_successful_adapter_is_scored_and_artifact_is_committed(self) -> None:
        benchmark = ParserBenchmark(self.gold)
        runs, scores = benchmark.run(self.pdf, self.root / "output", [SuccessfulFakeAdapter()])
        self.assertEqual(runs[0].status, ParserRunStatus.SUCCESS)
        self.assertTrue(Path(runs[0].artifacts["raw"]).exists())
        self.assertGreater(scores[0].score, 80)
        self.assertTrue((self.root / "output" / "report.md").exists())

    def test_failed_adapter_leaves_no_partial_directory(self) -> None:
        result = FailingFakeAdapter().run(uuid4(), self.pdf, self.root / "output")
        self.assertEqual(result.status, ParserRunStatus.FAILED)
        self.assertFalse((self.root / "output" / "failing").exists())

    def test_cloud_adapters_skip_without_explicit_configuration(self) -> None:
        old_grobid = os.environ.pop("GROBID_URL", None)
        old_mineru = os.environ.pop("MINERU_ALLOW_UPLOAD", None)
        try:
            grobid = GrobidAdapter().run(uuid4(), self.pdf, self.root / "grobid-output")
            mineru = MinerUAdapter().run(uuid4(), self.pdf, self.root / "mineru-output")
        finally:
            if old_grobid is not None:
                os.environ["GROBID_URL"] = old_grobid
            if old_mineru is not None:
                os.environ["MINERU_ALLOW_UPLOAD"] = old_mineru
        self.assertEqual(grobid.status, ParserRunStatus.SKIPPED)
        self.assertEqual(mineru.status, ParserRunStatus.SKIPPED)


if __name__ == "__main__":
    unittest.main()
