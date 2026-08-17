from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import UUID

from chemresearch_agent.domain.enums import EvidenceKind
from chemresearch_agent.domain.models import BoundingBox, DocumentParseResult, SourceBlock

from .base import PdfParserAdapter, normalize_text, sha256_file
from .models import ParserRunResult, ParserRunStatus

TEI = {"tei": "http://www.tei-c.org/ns/1.0"}


def _coordinates(raw: str | None) -> tuple[int, BoundingBox | None]:
    if not raw:
        return 1, None
    first = raw.split(";")[0].split(",")
    if len(first) != 5:
        return 1, None
    page, x, y, width, height = (float(part) for part in first)
    if width <= 0 or height <= 0:
        return max(int(page), 1), None
    return max(int(page), 1), BoundingBox(x0=x, y0=y, x1=x + width, y1=y + height)


class GrobidAdapter(PdfParserAdapter):
    name = "grobid"
    package_name = "httpx"
    deployment_points = 8

    def parse(self, document_id: UUID, pdf_path: Path, work_dir: Path) -> ParserRunResult:
        import httpx

        base_url = os.getenv("GROBID_URL")
        if not base_url:
            return ParserRunResult(
                parser_name=self.name,
                status=ParserRunStatus.SKIPPED,
                warnings=["GROBID_URL is not configured; no third-party demo was used."],
            )
        endpoint = base_url.rstrip("/") + "/api/processFulltextDocument"
        with pdf_path.open("rb") as stream:
            response = httpx.post(
                endpoint,
                files={"input": (pdf_path.name, stream, "application/pdf")},
                data=[
                    ("consolidateHeader", "2"),
                    ("includeRawCitations", "1"),
                    ("teiCoordinates", "figure"),
                    ("teiCoordinates", "biblStruct"),
                ],
                timeout=180,
            )
        response.raise_for_status()
        xml_text = response.text
        root = ET.fromstring(xml_text)
        blocks: list[SourceBlock] = []
        index = 0
        for element in root.findall(".//tei:body//tei:head", TEI) + root.findall(
            ".//tei:body//tei:p", TEI
        ):
            text = normalize_text("".join(element.itertext()))
            if not text:
                continue
            index += 1
            blocks.append(
                SourceBlock(
                    source_id=f"grobid-text-{index}",
                    page_number=1,
                    kind=EvidenceKind.TEXT,
                    text=text,
                    label="heading" if element.tag.endswith("head") else None,
                )
            )
        for figure in root.findall(".//tei:figure", TEI):
            caption = normalize_text("".join(figure.itertext()))
            page, bbox = _coordinates(figure.attrib.get("coords"))
            index += 1
            match = re.search(r"Figure\s+(\d+)", caption, re.IGNORECASE)
            blocks.append(
                SourceBlock(
                    source_id=f"grobid-figure-{index}",
                    page_number=page,
                    kind=EvidenceKind.FIGURE,
                    text=caption or None,
                    label=f"Figure {match.group(1)}" if match else "figure",
                    bounding_box=bbox,
                )
            )
        title = normalize_text(
            "".join((root.find(".//tei:titleStmt/tei:title", TEI) or ET.Element("x")).itertext())
        )
        authors = [
            normalize_text("".join(author.itertext()))
            for author in root.findall(".//tei:titleStmt/tei:author", TEI)
        ]
        doi_node = root.find('.//tei:idno[@type="DOI"]', TEI)
        journal_node = root.find(".//tei:monogr/tei:title", TEI)
        metadata = {
            "title": title,
            "authors": "; ".join(authors),
            "doi": normalize_text(doi_node.text or "") if doi_node is not None else "",
            "journal": normalize_text(journal_node.text or "") if journal_node is not None else "",
        }
        page_count = max((block.page_number for block in blocks), default=1)
        parsed = DocumentParseResult(
            document_id=document_id,
            file_name=pdf_path.name,
            file_hash=sha256_file(pdf_path),
            page_count=page_count,
            blocks=blocks,
            metadata={key: value for key, value in metadata.items() if value},
            warnings=[
                "GROBID paragraph coordinates were not requested; figure coordinates are retained."
            ],
        )
        xml_path = work_dir / "document.tei.xml"
        xml_path.write_text(xml_text, encoding="utf-8")
        return ParserRunResult(
            parser_name=self.name,
            status=ParserRunStatus.SUCCESS,
            document=parsed,
            markdown="\n\n".join(block.text for block in blocks if block.text),
            artifacts={"tei_xml": str(xml_path)},
            warnings=list(parsed.warnings),
        )
