from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import pymupdf

from chemresearch_agent.tools.pdf import PyMuPdfParser


def create_figure_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((40, 70), "Synthetic chemistry paper")
    page.insert_text((40, 115), "The transformation is summarized in Figure 1A.")
    page.draw_rect(pymupdf.Rect(45, 180, 555, 420), color=(0, 0, 1), width=2)
    page.insert_text((85, 280), "R-X + B2pin2 -> R-Bpin")
    page.insert_textbox(
        pymupdf.Rect(45, 440, 555, 485),
        "Figure 1. Synthetic reaction scheme used to test caption-anchored cropping.",
        fontsize=10,
    )
    document.save(path)
    document.close()


class PyMuPdfParserTests(unittest.TestCase):
    def test_parser_crops_and_links_figure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.pdf"
            create_figure_pdf(source)
            result = PyMuPdfParser(root / "artifacts").parse(uuid4(), source)
            self.assertEqual(result.page_count, 1)
            self.assertEqual(len(result.figures), 1)
            figure = result.figures[0]
            self.assertEqual(figure.label, "Figure 1")
            self.assertEqual(figure.page_number, 1)
            self.assertTrue(Path(figure.asset_path).is_file())
            self.assertEqual(len(figure.referenced_by_source_ids), 1)
            self.assertGreater(figure.bounding_box.y1 - figure.bounding_box.y0, 100)

    def test_parser_refuses_to_overwrite_existing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.pdf"
            create_figure_pdf(source)
            parser = PyMuPdfParser(root / "artifacts")
            document_id = uuid4()
            parser.parse(document_id, source)
            with self.assertRaises(FileExistsError):
                parser.parse(document_id, source)


if __name__ == "__main__":
    unittest.main()
