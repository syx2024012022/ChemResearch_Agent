from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pymupdf

from chemresearch_agent.tools.pdf import PyMuPdfParser

from .base import PdfParserAdapter
from .models import ParserRunResult, ParserRunStatus


class PyMuPdfAdapter(PdfParserAdapter):
    name = "pymupdf"
    package_name = "pymupdf"
    deployment_points = 15

    def parse(self, document_id: UUID, pdf_path: Path, work_dir: Path) -> ParserRunResult:
        document = PyMuPdfParser(work_dir).parse(document_id, pdf_path)
        artifact_dir = work_dir / str(document_id)
        previews = artifact_dir / "previews"
        previews.mkdir()
        source = pymupdf.open(pdf_path)
        try:
            for page_number in {1, 3, 6, 10, 13}:
                if page_number <= source.page_count:
                    pixmap = source[page_number - 1].get_pixmap(dpi=144, alpha=False)
                    pixmap.save(previews / f"page-{page_number:02d}.png")
        finally:
            source.close()
        markdown_path = artifact_dir / "document.md"
        json_path = artifact_dir / "document.json"
        return ParserRunResult(
            parser_name=self.name,
            status=ParserRunStatus.SUCCESS,
            document=document,
            markdown=markdown_path.read_text(encoding="utf-8"),
            artifacts={"markdown": str(markdown_path), "json": str(json_path)},
            warnings=list(document.warnings),
        )
