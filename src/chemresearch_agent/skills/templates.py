from __future__ import annotations

from chemresearch_agent.domain.enums import SlideType
from chemresearch_agent.domain.models import TemplateSlotSpec, TemplateSpec


class BuiltinTemplateRegistry:
    def __init__(self) -> None:
        self._templates = {item.template_id: item for item in _templates()}

    def get(self, template_id: str) -> TemplateSpec:
        try:
            return self._templates[template_id]
        except KeyError as exc:
            raise ValueError(f"unknown template: {template_id}") from exc

    def all(self) -> list[TemplateSpec]:
        return list(self._templates.values())


def _templates() -> list[TemplateSpec]:
    def spec(template_id: str, slide_type: SlideType, layout: str, image_count: int = 1):
        slots = [TemplateSlotSpec(name="message", kind="text", max_characters=240)]
        slots.extend(
            TemplateSlotSpec(name=f"figure_{index + 1}", kind="image", required=False)
            for index in range(image_count)
        )
        return TemplateSpec(
            template_id=template_id,
            slide_type=slide_type,
            layout=layout,
            slots=slots,
            renderer_version="artifact-tool-0.1",
        )

    title = TemplateSpec(
        template_id="title_paper_toc",
        slide_type=SlideType.TITLE,
        layout="title_paper_toc",
        slots=[
            TemplateSlotSpec(name="message", kind="text", max_characters=240),
            TemplateSlotSpec(name="authors", kind="text", max_characters=240),
            TemplateSlotSpec(name="publication", kind="text", max_characters=240),
            TemplateSlotSpec(name="toc_graphic", kind="image", required=False),
        ],
        renderer_version="artifact-tool-0.1",
    )
    return [
        title,
        spec("background_visual", SlideType.BACKGROUND, "image_right"),
        spec("research_gap_visual", SlideType.RESEARCH_GAP, "image_left"),
        spec("reaction_single", SlideType.REACTION_DESIGN, "image_full"),
        spec("optimization_single", SlideType.OPTIMIZATION, "image_full"),
        spec("scope_single", SlideType.SUBSTRATE_SCOPE, "image_full"),
        spec("mechanism_single", SlideType.MECHANISM, "image_full"),
        spec("application_double", SlideType.APPLICATION, "two_images", 2),
        spec("limitation_visual", SlideType.LIMITATION, "image_right"),
        spec("conclusion_visual", SlideType.CONCLUSION, "image_left"),
        spec("single_with_callout", SlideType.APPLICATION, "image_right"),
        spec("image_full", SlideType.APPLICATION, "image_full"),
        spec("multipanel_full", SlideType.APPLICATION, "multipanel_full"),
        spec("two_panels_fill", SlideType.APPLICATION, "two_panels_fill", 2),
        spec("panel_triptych", SlideType.APPLICATION, "panel_triptych", 3),
        spec("weighted_two_images", SlideType.APPLICATION, "weighted_two_images", 2),
        spec(
            "stacked_mechanism_overview",
            SlideType.REACTION_DESIGN,
            "stacked_mechanism_overview",
            2,
        ),
    ]


DEFAULT_TEMPLATE_BY_TYPE = {
    SlideType.TITLE: "title_paper_toc",
    SlideType.BACKGROUND: "background_visual",
    SlideType.RESEARCH_GAP: "research_gap_visual",
    SlideType.REACTION_DESIGN: "reaction_single",
    SlideType.OPTIMIZATION: "optimization_single",
    SlideType.SUBSTRATE_SCOPE: "scope_single",
    SlideType.MECHANISM: "mechanism_single",
    SlideType.APPLICATION: "application_double",
    SlideType.LIMITATION: "limitation_visual",
    SlideType.CONCLUSION: "conclusion_visual",
}
