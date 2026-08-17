from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import UUID

from chemresearch_agent.domain.enums import EvidenceKind
from chemresearch_agent.domain.models import BoundingBox, DocumentParseResult, SourceBlock

from .base import PdfParserAdapter, normalize_text, sha256_file
from .models import ParserRunResult, ParserRunStatus


class PdfPlumberAdapter(PdfParserAdapter):
    name = "pdfplumber"
    package_name = "pdfplumber"
    deployment_points = 14

    def parse(self, document_id: UUID, pdf_path: Path, work_dir: Path) -> ParserRunResult:
        import pdfplumber
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        metadata = {
            str(key).lstrip("/"): str(value)
            for key, value in (reader.metadata or {}).items()
            if value
        }
        blocks: list[SourceBlock] = []
        markdown_pages: list[str] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_number, page in enumerate(pdf.pages, 1):
                page_text = normalize_text(page.extract_text(use_text_flow=True) or "")
                markdown_pages.append(f"## Page {page_number}\n\n{page_text}")
                words = page.extract_words(
                    use_text_flow=True,
                    keep_blank_chars=False,
                    extra_attrs=["fontname", "size"],
                )
                lines: list[list[dict]] = []
                for word in words:
                    if not lines or abs(float(word["top"]) - float(lines[-1][0]["top"])) > 2.5:
                        lines.append([word])
                    else:
                        lines[-1].append(word)
                for line_number, line in enumerate(lines, 1):
                    line = sorted(line, key=lambda word: float(word["x0"]))
                    text = normalize_text(" ".join(str(word["text"]) for word in line))
                    if not text:
                        continue
                    x0 = min(float(word["x0"]) for word in line)
                    x1 = max(float(word["x1"]) for word in line)
                    y0 = min(float(word["top"]) for word in line)
                    y1 = max(float(word["bottom"]) for word in line)
                    figure_match = re.match(r"Figure\s+(\d+)\.", text, re.IGNORECASE)
                    blocks.append(
                        SourceBlock(
                            source_id=f"p{page_number}-line-{line_number}",
                            page_number=page_number,
                            kind=EvidenceKind.TEXT,
                            text=text,
                            label=(f"Figure {figure_match.group(1)}" if figure_match else None),
                            bounding_box=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1),
                        )
                    )
                for image_number, image in enumerate(page.images, 1):
                    x0, x1 = sorted((float(image["x0"]), float(image["x1"])))
                    y0, y1 = sorted((float(image["top"]), float(image["bottom"])))
                    if x1 <= x0 or y1 <= y0:
                        continue
                    blocks.append(
                        SourceBlock(
                            source_id=f"p{page_number}-image-{image_number}",
                            page_number=page_number,
                            kind=EvidenceKind.FIGURE,
                            bounding_box=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1),
                        )
                    )
        markdown = "\n\n".join(markdown_pages)
        parsed = DocumentParseResult(
            document_id=document_id,
            file_name=pdf_path.name,
            file_hash=sha256_file(pdf_path),
            page_count=len(reader.pages),
            blocks=blocks,
            metadata=metadata,
            warnings=[
                "Vector reaction schemes are represented by page geometry, not standalone assets."
            ],
        )
        markdown_path = work_dir / "document.md"
        json_path = work_dir / "document.json"
        markdown_path.write_text(markdown, encoding="utf-8")
        json_path.write_text(
            json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return ParserRunResult(
            parser_name=self.name,
            status=ParserRunStatus.SUCCESS,
            document=parsed,
            markdown=markdown,
            artifacts={"markdown": str(markdown_path), "json": str(json_path)},
            warnings=list(parsed.warnings),
        )
