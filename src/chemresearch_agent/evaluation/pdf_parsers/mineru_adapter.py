from __future__ import annotations

import json
import os
import re
from pathlib import Path
from uuid import UUID

from chemresearch_agent.domain.enums import EvidenceKind
from chemresearch_agent.domain.models import DocumentParseResult, SourceBlock

from .base import PdfParserAdapter, normalize_text, sha256_file
from .models import ParserRunResult, ParserRunStatus


class MinerUAdapter(PdfParserAdapter):
    name = "mineru_cloud"
    package_name = "mineru-open-sdk"
    deployment_points = 8

    def parse(self, document_id: UUID, pdf_path: Path, work_dir: Path) -> ParserRunResult:
        if os.getenv("MINERU_ALLOW_UPLOAD") != "1":
            return ParserRunResult(
                parser_name=self.name,
                status=ParserRunStatus.SKIPPED,
                warnings=["MINERU_ALLOW_UPLOAD=1 is required for explicit cloud upload consent."],
            )
        from mineru import MinerU

        token = os.getenv("MINERU_TOKEN")
        client = MinerU(token) if token else MinerU()
        result = client.extract(str(pdf_path)) if token else client.flash_extract(str(pdf_path))
        markdown = str(getattr(result, "markdown", "") or "")
        images = getattr(result, "images", None) or []
        blocks: list[SourceBlock] = []
        page_number = 1
        for index, chunk in enumerate(re.split(r"(?=^#{1,3}\s)|\n\n+", markdown, flags=re.M), 1):
            text = normalize_text(chunk)
            if not text:
                continue
            page_marker = re.search(r"(?:page|页)[ _-]?(\d+)", text, re.IGNORECASE)
            if page_marker:
                page_number = max(int(page_marker.group(1)), 1)
            match = re.match(r"Figure\s+(\d+)\.", text, re.IGNORECASE)
            blocks.append(
                SourceBlock(
                    source_id=f"mineru-text-{index}",
                    page_number=page_number,
                    kind=EvidenceKind.TEXT,
                    text=text,
                    label=f"Figure {match.group(1)}" if match else None,
                )
            )
        doi_match = re.search(r"10\.1021/[A-Za-z0-9.]+", markdown)
        parsed = DocumentParseResult(
            document_id=document_id,
            file_name=pdf_path.name,
            file_hash=sha256_file(pdf_path),
            page_count=max((block.page_number for block in blocks), default=1),
            blocks=blocks,
            metadata={"doi": doi_match.group(0)} if doi_match else {},
            warnings=[
                "MinerU Markdown does not guarantee page coordinates; raw cloud output is retained."
            ],
        )
        markdown_path = work_dir / "document.md"
        result_path = work_dir / "result-summary.json"
        markdown_path.write_text(markdown, encoding="utf-8")
        result_path.write_text(
            json.dumps({"images": [str(image) for image in images]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return ParserRunResult(
            parser_name=self.name,
            status=ParserRunStatus.PARTIAL,
            document=parsed,
            markdown=markdown,
            artifacts={"markdown": str(markdown_path), "summary": str(result_path)},
            warnings=list(parsed.warnings),
        )
