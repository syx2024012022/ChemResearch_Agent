from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw

from chemresearch_agent.domain.enums import EvidenceKind, PresentationPurpose, SlideType
from chemresearch_agent.domain.models import (
    BoundingBox,
    DocumentParseResult,
    EvidenceRef,
    FigureRecord,
    PaperAnalysis,
    PaperMetadata,
    PresentationRequirements,
    SlidePlan,
    SlidePlanItem,
    SourceBlock,
)
from chemresearch_agent.skills.composer import (
    RuleBasedPresentationComposerSkill,
    _display_title,
    _is_quantitative_plot,
    _limit_title,
)
from chemresearch_agent.skills.figure_layout import DeterministicFigureLayoutAnalyzer


def _image(path: Path, separators: list[int] | None = None) -> None:
    image = Image.new("RGB", (500, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((90, 60, 240, 260), outline="black", width=4)
    draw.ellipse((260, 100, 410, 280), outline="black", width=4)
    draw.ellipse((100, 590, 250, 820), outline="black", width=4)
    draw.ellipse((270, 610, 410, 840), outline="black", width=4)
    for y in separators or []:
        draw.line((15, y, 485, y), fill="black", width=4)
    image.save(path)


def _figure(path: Path, number: int, document_id, caption: str) -> tuple[FigureRecord, EvidenceRef]:
    source_id = f"p1-figure-{number}"
    figure = FigureRecord(
        figure_id=f"figure-{number}",
        label=f"Figure {number}",
        page_number=1,
        caption_source_id=source_id,
        caption=caption,
        asset_path=str(path),
        bounding_box=BoundingBox(x0=0, y0=0, x1=500, y1=900),
    )
    ref = EvidenceRef(
        source_id=source_id,
        document_id=document_id,
        page_number=1,
        kind=EvidenceKind.TEXT,
        label=f"Figure {number}",
    )
    return figure, ref


class FigureLayoutAutomationTests(unittest.TestCase):
    def test_english_title_fallback_is_generic_not_paper_specific(self) -> None:
        self.assertEqual(
            _display_title("A long paper-specific claim", [], "en", SlideType.MECHANISM),
            "Mechanistic Proposal and Evidence",
        )

    def test_title_limit_preserves_words_and_single_line(self) -> None:
        title = _limit_title(
            "A deliberately long mechanistic title that would otherwise wrap in the banner",
            54,
        )
        self.assertLessEqual(len(title), 54)
        self.assertNotIn("\n", title)
        self.assertTrue(title.endswith("…"))

    def test_quantitative_plot_detection_is_semantic(self) -> None:
        self.assertTrue(_is_quantitative_plot("Figure 4. Linear free-energy correlation."))
        self.assertTrue(_is_quantitative_plot("Figure 5. Kinetic plot for catalyst loading."))
        self.assertFalse(_is_quantitative_plot("Figure 6. Representative substrate scope."))

    def test_two_panel_portrait_is_safely_split(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "figure.png"
            _image(source, [450])
            figure, _ = _figure(source, 1, uuid4(), "Figure 1. (A) Cycle. (B) Scope.")
            profile = DeterministicFigureLayoutAnalyzer().analyze(figure, root / "derived")
            self.assertEqual(profile.recommended_layout, "two_panels_fill")
            self.assertEqual([panel.panel_label for panel in profile.panels], ["A", "B"])
            self.assertTrue(all(Path(panel.asset_path).exists() for panel in profile.panels))

    def test_unconfirmed_boundaries_keep_whole_figure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "figure.png"
            _image(source)
            figure, _ = _figure(source, 1, uuid4(), "Figure 1. (A) Cycle. (B) Scope.")
            profile = DeterministicFigureLayoutAnalyzer().analyze(figure, root / "derived")
            self.assertFalse(profile.panels)
            self.assertIn("panel_boundary_unconfirmed", profile.warnings)

    def test_four_panel_portrait_uses_safe_two_by_two_recomposition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "figure.png"
            _image(source)
            figure, _ = _figure(
                source,
                1,
                uuid4(),
                "Figure 1. (A) Labeling. (B) Exchange. (C) KIE. (D) Mechanism.",
            )
            profile = DeterministicFigureLayoutAnalyzer().analyze(figure, root / "derived")
            self.assertEqual(profile.recommended_layout, "two_panels_fill")
            self.assertEqual(
                [panel.panel_label for panel in profile.panels],
                ["A-B", "C-D"],
            )

    def test_composer_auto_splits_within_range_and_preserves_origin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document_id = uuid4()
            figures, refs = [], []
            for number in (1, 2):
                path = root / f"figure-{number}.png"
                _image(path)
                figure, ref = _figure(
                    path,
                    number,
                    document_id,
                    f"Figure {number}. (A) Study. (B) Mechanism. (C) Scope.",
                )
                figures.append(figure)
                refs.append(ref)
            document = DocumentParseResult(
                document_id=document_id,
                file_name="paper.pdf",
                file_hash="hash",
                page_count=1,
                figures=figures,
                blocks=[
                    SourceBlock(
                        source_id="body",
                        page_number=1,
                        kind=EvidenceKind.TEXT,
                        text="The study establishes a mechanistic basis for the reaction.",
                    )
                ],
            )
            plan = SlidePlan(
                title="Test",
                rationale="Test",
                slides=[
                    SlidePlanItem(
                        slide_id="s1",
                        slide_type=SlideType.APPLICATION,
                        purpose="Show evidence",
                        key_message="Evidence and scope",
                        source_refs=refs,
                    ),
                    SlidePlanItem(
                        slide_id="s2",
                        slide_type=SlideType.APPLICATION,
                        purpose="Section",
                        key_message="Section",
                    ),
                    SlidePlanItem(
                        slide_id="s3",
                        slide_type=SlideType.CONCLUSION,
                        purpose="Conclusion",
                        key_message="Conclusion",
                    ),
                ],
            )
            requirements = PresentationRequirements(
                purpose=PresentationPurpose.GROUP_MEETING,
                min_slide_count=3,
                max_slide_count=4,
                title_include_toc_graphic=False,
                require_visual_each_slide=False,
            )
            contents = RuleBasedPresentationComposerSkill().compose(
                plan,
                PaperAnalysis(document_id=document_id, metadata=PaperMetadata(title="Test")),
                document,
                requirements,
                root / "composition",
            )
            self.assertEqual(len(contents), 4)
            self.assertEqual(
                [content.origin_plan_slide_id for content in contents[:2]], ["s1", "s1"]
            )
            self.assertTrue(all(content.layout_decision.auto_split for content in contents[:2]))

    def test_layout_quality_can_relax_page_limit_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document_id = uuid4()
            figures, refs = [], []
            for number in (1, 2):
                path = root / f"figure-{number}.png"
                _image(path)
                figure, ref = _figure(
                    path,
                    number,
                    document_id,
                    f"Figure {number}. (A) Study. (B) Mechanism. (C) Scope.",
                )
                figures.append(figure)
                refs.append(ref)
            document = DocumentParseResult(
                document_id=document_id,
                file_name="paper.pdf",
                file_hash="hash",
                page_count=1,
                figures=figures,
            )
            plan = SlidePlan(
                title="Test",
                rationale="Test",
                slides=[
                    SlidePlanItem(
                        slide_id="s1",
                        slide_type=SlideType.APPLICATION,
                        purpose="Evidence",
                        key_message="Evidence",
                        source_refs=refs,
                    ),
                    SlidePlanItem(
                        slide_id="s2",
                        slide_type=SlideType.APPLICATION,
                        purpose="Section",
                        key_message="Section",
                    ),
                    SlidePlanItem(
                        slide_id="s3",
                        slide_type=SlideType.CONCLUSION,
                        purpose="Conclusion",
                        key_message="Conclusion",
                    ),
                ],
            )
            contents = RuleBasedPresentationComposerSkill().compose(
                plan,
                PaperAnalysis(document_id=document_id, metadata=PaperMetadata(title="Test")),
                document,
                PresentationRequirements(
                    purpose=PresentationPurpose.GROUP_MEETING,
                    min_slide_count=3,
                    max_slide_count=3,
                    title_include_toc_graphic=False,
                    require_visual_each_slide=False,
                ),
                root / "composition",
            )
            self.assertEqual(len(contents), 4)
            self.assertIn(
                "slide_limit_relaxed_for_layout_quality", contents[0].composition_warnings
            )

    def test_portrait_and_wide_figures_are_never_combined(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document_id = uuid4()
            portrait_path = root / "portrait.png"
            wide_path = root / "wide.png"
            _image(portrait_path, [450])
            Image.new("RGB", (1000, 420), "white").save(wide_path)
            portrait, portrait_ref = _figure(
                portrait_path, 1, document_id, "Figure 1. (A) Evidence. (B) Scope."
            )
            wide, wide_ref = _figure(wide_path, 2, document_id, "Figure 2. Wide reaction scheme.")
            document = DocumentParseResult(
                document_id=document_id,
                file_name="paper.pdf",
                file_hash="hash",
                page_count=1,
                figures=[portrait, wide],
            )
            plan = SlidePlan(
                title="Test",
                rationale="Test",
                slides=[
                    SlidePlanItem(
                        slide_id="s1",
                        slide_type=SlideType.APPLICATION,
                        purpose="Compare",
                        key_message="Compare",
                        source_refs=[portrait_ref, wide_ref],
                    )
                ],
            )
            contents = RuleBasedPresentationComposerSkill().compose(
                plan,
                PaperAnalysis(document_id=document_id, metadata=PaperMetadata(title="Test")),
                document,
                PresentationRequirements(
                    purpose=PresentationPurpose.GROUP_MEETING,
                    min_slide_count=3,
                    max_slide_count=3,
                    title_include_toc_graphic=False,
                ),
                root / "composition",
            )
            self.assertEqual(len(contents), 2)
            self.assertTrue(all(content.layout_decision.auto_split for content in contents))


if __name__ == "__main__":
    unittest.main()
