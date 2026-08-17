from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from chemresearch_agent.domain.enums import EvidenceKind
from chemresearch_agent.domain.models import (
    BoundingBox,
    DocumentParseResult,
    FigureRecord,
    SourceBlock,
)

if TYPE_CHECKING:
    import pymupdf

VISUAL_CAPTION = re.compile(
    r"^(Figure|Scheme|Table)\s+(\d+)\b[.:]?", re.IGNORECASE
)
VISUAL_REFERENCE = re.compile(
    r"\b(Figure|Scheme|Table)\s+(\d+)(?:[A-Z])?\b", re.IGNORECASE
)


def _normalize_text(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\u2011", "-").replace("\u2212", "-")
    return re.sub(r"\s+", " ", text).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PyMuPdfParser:
    """Production PDF parser with evidence coordinates and caption-anchored figure crops."""

    def __init__(self, artifact_root: Path, *, crop_dpi: int = 200) -> None:
        self._artifact_root = artifact_root
        self._crop_dpi = crop_dpi

    def parse(self, document_id: UUID, path: Path) -> DocumentParseResult:
        if not path.is_file():
            raise FileNotFoundError(path)
        import pymupdf

        destination = self._artifact_root / str(document_id)
        if destination.exists():
            raise FileExistsError(f"document artifacts already exist: {destination}")
        figures_dir = destination / "figures"
        destination.mkdir(parents=True, exist_ok=True)
        figures_dir.mkdir(parents=True, exist_ok=True)

        document = pymupdf.open(path)
        try:
            blocks_by_page: dict[int, list[SourceBlock]] = {}
            markdown_pages: list[str] = []
            for page_index, page in enumerate(document):
                page_number = page_index + 1
                raw_blocks = [
                    block for block in page.get_text("blocks", sort=True) if block[6] == 0
                ]
                page_blocks: list[SourceBlock] = []
                page_texts: list[str] = []
                for block_index, raw in enumerate(raw_blocks, 1):
                    text = _normalize_text(raw[4])
                    if not text:
                        continue
                    match = VISUAL_CAPTION.match(text)
                    page_blocks.append(
                        SourceBlock(
                            source_id=f"p{page_number}-text-{block_index}",
                            page_number=page_number,
                            kind=EvidenceKind.TEXT,
                            text=text,
                            label=f"{match.group(1).title()} {match.group(2)}" if match else None,
                            bounding_box=BoundingBox(x0=raw[0], y0=raw[1], x1=raw[2], y1=raw[3]),
                        )
                    )
                    page_texts.append(text)
                blocks_by_page[page_number] = page_blocks
                markdown_pages.append(f"## Page {page_number}\n\n" + "\n\n".join(page_texts))

            all_blocks = [block for page_blocks in blocks_by_page.values() for block in page_blocks]
            figures = self._extract_figures(document, blocks_by_page, figures_dir)
            toc_graphic = self._extract_toc_graphic(document, figures_dir)
            if toc_graphic is not None:
                figures.insert(0, toc_graphic)
                all_blocks.append(
                    SourceBlock(
                        source_id=toc_graphic.caption_source_id,
                        page_number=1,
                        kind=EvidenceKind.TEXT,
                        text="TOC Graphic / Graphical Abstract",
                        label=toc_graphic.label,
                        bounding_box=toc_graphic.bounding_box,
                    )
                )
            references: dict[str, list[str]] = {figure.label: [] for figure in figures}
            caption_ids = {figure.caption_source_id for figure in figures}
            for block in all_blocks:
                if block.source_id in caption_ids or not block.text:
                    continue
                for kind, number in VISUAL_REFERENCE.findall(block.text):
                    label = f"{kind.title()} {int(number)}"
                    if label in references and block.source_id not in references[label]:
                        references[label].append(block.source_id)
            figures = [
                figure.model_copy(update={"referenced_by_source_ids": references[figure.label]})
                for figure in figures
            ]
            for figure in figures:
                all_blocks.append(
                    SourceBlock(
                        source_id=figure.figure_id,
                        page_number=figure.page_number,
                        kind=EvidenceKind.FIGURE,
                        asset_path=figure.asset_path,
                        label=figure.label,
                        bounding_box=figure.bounding_box,
                    )
                )

            markdown = "\n\n".join(markdown_pages)
            metadata = {key: str(value) for key, value in document.metadata.items() if value}
            first_page = markdown_pages[0] if markdown_pages else ""
            doi_match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", first_page)
            if doi_match:
                metadata["doi"] = doi_match.group(0)
            warnings = []
            if not figures:
                warnings.append(
                    "No Figure/Scheme/Table captions were detected; no crops were generated."
                )
            result = DocumentParseResult(
                document_id=document_id,
                file_name=path.name,
                file_hash=_sha256(path),
                page_count=document.page_count,
                blocks=all_blocks,
                figures=figures,
                metadata=metadata,
                warnings=warnings,
            )
            (destination / "document.md").write_text(markdown, encoding="utf-8")
            (destination / "document.json").write_text(
                json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return result
        except Exception:
            for child in sorted(destination.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            destination.rmdir()
            raise
        finally:
            document.close()

    def _extract_figures(
        self,
        document: pymupdf.Document,
        blocks_by_page: dict[int, list[SourceBlock]],
        figures_dir: Path,
    ) -> list[FigureRecord]:
        import pymupdf

        figures: list[FigureRecord] = []
        for page_number, blocks in blocks_by_page.items():
            page = document[page_number - 1]
            captions = [
                block for block in blocks if block.label and VISUAL_CAPTION.match(block.text or "")
            ]
            for caption in captions:
                kind, number_text = caption.label.split()
                number = int(number_text)
                crop = (
                    self._estimate_scheme_or_table_crop(page.rect, caption, captions)
                    if kind in {"Scheme", "Table"}
                    else self._estimate_crop(page.rect, caption, blocks)
                )
                asset = figures_dir / f"{kind.casefold()}-{number:02d}-page-{page_number:02d}.png"
                page.get_pixmap(
                    clip=pymupdf.Rect(crop.x0, crop.y0, crop.x1, crop.y1),
                    dpi=self._crop_dpi,
                    alpha=False,
                ).save(asset)
                figures.append(
                    FigureRecord(
                        figure_id=f"p{page_number}-{kind.casefold()}-{number}",
                        label=f"{kind} {number}",
                        page_number=page_number,
                        caption_source_id=caption.source_id,
                        caption=caption.text or "",
                        asset_path=str(asset),
                        bounding_box=crop,
                        confidence=0.8,
                    )
                )
        order = {"Figure": 0, "Scheme": 1, "Table": 2}
        return sorted(
            figures,
            key=lambda figure: (
                figure.page_number,
                order.get(figure.label.split()[0], 9),
                int(figure.label.split()[1]),
            ),
        )

    def _extract_toc_graphic(
        self, document: pymupdf.Document, figures_dir: Path
    ) -> FigureRecord | None:
        """Extract a prominent first-page graphical abstract when present."""
        import pymupdf

        page = document[0]
        page_area = page.rect.width * page.rect.height
        candidates = []
        for image in page.get_image_info(xrefs=True):
            x0, y0, x1, y1 = image["bbox"]
            width, height = x1 - x0, y1 - y0
            if (
                width * height >= page_area * 0.035
                and x0 >= page.rect.width * 0.35
                and y0 <= page.rect.height * 0.6
                and width / max(height, 1) >= 1.2
            ):
                candidates.append((width * height, pymupdf.Rect(x0, y0, x1, y1)))
        if not candidates:
            return None
        _, rect = max(candidates, key=lambda item: item[0])
        asset = figures_dir / "toc-graphic-page-01.png"
        page.get_pixmap(clip=rect, dpi=self._crop_dpi, alpha=False).save(asset)
        box = BoundingBox(x0=rect.x0, y0=rect.y0, x1=rect.x1, y1=rect.y1)
        return FigureRecord(
            figure_id="p1-toc-graphic",
            label="TOC Graphic",
            page_number=1,
            caption_source_id="p1-toc-text",
            caption="TOC Graphic / Graphical Abstract",
            asset_path=str(asset),
            bounding_box=box,
            crop_method="embedded_image_bbox",
            confidence=0.9,
        )

    @staticmethod
    def _estimate_scheme_or_table_crop(
        page_rect: pymupdf.Rect,
        caption: SourceBlock,
        captions: list[SourceBlock],
    ) -> BoundingBox:
        assert caption.bounding_box is not None
        box = caption.bounding_box
        page_width = page_rect.width
        margin = max(18.0, page_width * 0.035)
        full_width = box.x0 < page_width * 0.2 and box.x1 >= page_width * 0.54
        if full_width:
            x0, x1, side = margin, page_width - margin, "full"
        elif box.x0 < page_width / 2:
            x0, x1, side = margin, page_width / 2 - 6, "left"
        else:
            x0, x1, side = page_width / 2 + 6, page_width - margin, "right"

        if caption.label and caption.label.startswith("Table"):
            return BoundingBox(
                x0=x0,
                y0=box.y1 + 3,
                x1=x1,
                # Preserve trailing footnotes and ligand structures commonly placed
                # below a table body; losing them here cannot be repaired by layout.
                y1=min(page_rect.y1 - 92, box.y1 + page_rect.height * 0.52),
            )

        previous_bottom = page_rect.y0 + 24
        for other in captions:
            if other.source_id == caption.source_id or other.bounding_box is None:
                continue
            other_box = other.bounding_box
            if other_box.y1 >= box.y0:
                continue
            other_full = (
                other_box.x0 < page_width * 0.2 and other_box.x1 >= page_width * 0.54
            )
            same_side = (
                side == "full"
                or other_full
                or (side == "left" and other_box.x0 < page_width / 2)
                or (side == "right" and other_box.x0 >= page_width / 2)
            )
            if same_side:
                previous_bottom = max(previous_bottom, other_box.y1 + 8)
        return BoundingBox(x0=x0, y0=previous_bottom, x1=x1, y1=box.y0 - 3)

    @staticmethod
    def _estimate_crop(
        page_rect: pymupdf.Rect,
        caption: SourceBlock,
        blocks: list[SourceBlock],
    ) -> BoundingBox:
        assert caption.bounding_box is not None
        box = caption.bounding_box
        page_width = page_rect.width
        margin = max(18.0, page_width * 0.035)
        full_width = (box.x1 - box.x0) >= page_width * 0.62
        if full_width:
            x0, x1 = margin, page_width - margin
        elif (box.x0 + box.x1) / 2 < page_width / 2:
            x0, x1 = margin, page_width / 2 - 6
        else:
            x0, x1 = page_width / 2 + 6, page_width - margin

        candidates = [
            other.bounding_box
            for other in blocks
            if other.source_id != caption.source_id
            and other.bounding_box is not None
            and other.bounding_box.y1 < box.y0 - 3
            and other.bounding_box.x1 > x0
            and other.bounding_box.x0 < x1
        ]
        nearest_bottom = max((candidate.y1 for candidate in candidates), default=page_rect.y0 + 24)
        y0 = min(nearest_bottom + 3, box.y0 - 24)
        y1 = box.y0 - 3
        if y1 - y0 < 36:
            y0 = max(page_rect.y0 + 18, y1 - min(220, page_rect.height * 0.35))
        return BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
