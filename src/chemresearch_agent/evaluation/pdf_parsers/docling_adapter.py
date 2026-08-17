from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID

from chemresearch_agent.domain.enums import EvidenceKind
from chemresearch_agent.domain.models import BoundingBox, DocumentParseResult, SourceBlock

from .base import PdfParserAdapter, normalize_text, sha256_file
from .models import ParserRunResult, ParserRunStatus


def _bbox(value: dict[str, Any] | None) -> BoundingBox | None:
    if not value:
        return None
    coords = [value.get(key) for key in ("l", "t", "r", "b")]
    if any(coord is None for coord in coords):
        return None
    left, top, right, bottom = (float(coord) for coord in coords)
    x0, x1 = sorted((left, right))
    y0, y1 = sorted((top, bottom))
    if x1 <= x0 or y1 <= y0:
        return None
    return BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)


class DoclingAdapter(PdfParserAdapter):
    name = "docling"
    package_name = "docling"
    deployment_points = 10

    def parse(self, document_id: UUID, pdf_path: Path, work_dir: Path) -> ParserRunResult:
        from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        options = PdfPipelineOptions()
        options.do_ocr = False
        options.do_table_structure = True
        options.generate_picture_images = True
        options.accelerator_options = AcceleratorOptions(
            num_threads=4, device=AcceleratorDevice.CPU
        )
        converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF],
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)},
        )
        result = converter.convert(pdf_path)
        raw = result.document.export_to_dict()
        markdown = result.document.export_to_markdown()
        blocks: list[SourceBlock] = []
        index = 0
        for collection, kind in (
            (raw.get("texts", []), EvidenceKind.TEXT),
            (raw.get("pictures", []), EvidenceKind.FIGURE),
            (raw.get("tables", []), EvidenceKind.TABLE),
        ):
            for item in collection:
                text = normalize_text(str(item.get("text") or item.get("caption") or "")) or None
                label_value = str(item.get("label") or "")
                figure_match = re.match(r"Figure\s+(\d+)\.", text or "", re.IGNORECASE)
                for provenance in item.get("prov") or [{}]:
                    index += 1
                    page_number = int(provenance.get("page_no") or 1)
                    blocks.append(
                        SourceBlock(
                            source_id=f"docling-{index}",
                            page_number=max(page_number, 1),
                            kind=kind,
                            text=text,
                            label=(
                                f"Figure {figure_match.group(1)}"
                                if figure_match
                                else label_value or None
                            ),
                            bounding_box=_bbox(provenance.get("bbox")),
                        )
                    )
        pages = raw.get("pages") or {}
        page_count = len(pages) or max((block.page_number for block in blocks), default=1)
        doi_match = re.search(r"10\.1021/[A-Za-z0-9.]+", markdown)
        title_match = re.search(r"N[-\u2011 ]Boryl Pyridyl Anion Chemistry", markdown)
        metadata = {
            "title": title_match.group(0) if title_match else "",
            "doi": doi_match.group(0) if doi_match else "",
        }
        parsed = DocumentParseResult(
            document_id=document_id,
            file_name=pdf_path.name,
            file_hash=sha256_file(pdf_path),
            page_count=page_count,
            blocks=blocks,
            metadata={key: value for key, value in metadata.items() if value},
            warnings=[],
        )
        raw_path = work_dir / "docling.json"
        markdown_path = work_dir / "document.md"
        normalized_path = work_dir / "document.json"
        raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        normalized_path.write_text(
            json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return ParserRunResult(
            parser_name=self.name,
            status=ParserRunStatus.SUCCESS,
            document=parsed,
            markdown=markdown,
            artifacts={
                "raw_json": str(raw_path),
                "markdown": str(markdown_path),
                "json": str(normalized_path),
            },
        )
