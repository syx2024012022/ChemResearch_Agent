import unittest
from uuid import uuid4

from pydantic import ValidationError

from chemresearch_agent.domain.enums import ClaimBasis, EvidenceKind, SlideType
from chemresearch_agent.domain.models import (
    EvidenceRef,
    GroundedClaim,
    SlidePlan,
    SlidePlanItem,
    TemplateSlotSpec,
    TemplateSpec,
)


class DomainModelTests(unittest.TestCase):
    def test_explicit_claim_requires_evidence(self) -> None:
        with self.assertRaises(ValidationError):
            GroundedClaim(text="A catalyst was used", basis=ClaimBasis.EXPLICIT)

    def test_grounded_claim_accepts_evidence(self) -> None:
        evidence = EvidenceRef(
            source_id="p3-text-1",
            document_id=uuid4(),
            page_number=3,
            kind=EvidenceKind.TEXT,
            excerpt="The reaction proceeded...",
        )
        claim = GroundedClaim(
            text="The reaction uses photoredox catalysis",
            basis=ClaimBasis.EXPLICIT,
            evidence=[evidence],
        )
        self.assertEqual(claim.evidence[0].page_number, 3)

    def test_slide_plan_sums_duration(self) -> None:
        plan = SlidePlan(
            title="Test presentation",
            rationale="Short report",
            slides=[
                SlidePlanItem(
                    slide_id="s1",
                    slide_type=SlideType.TITLE,
                    purpose="Open",
                    key_message="Paper identity",
                    estimated_seconds=20,
                ),
                SlidePlanItem(
                    slide_id="s2",
                    slide_type=SlideType.CONCLUSION,
                    purpose="Close",
                    key_message="Main conclusion",
                    estimated_seconds=40,
                ),
            ],
        )
        self.assertEqual(plan.estimated_duration_seconds, 60)

    def test_template_slot_names_must_be_unique(self) -> None:
        with self.assertRaises(ValidationError):
            TemplateSpec(
                template_id="reaction_01",
                slide_type=SlideType.REACTION_DESIGN,
                layout="two_column",
                renderer_version="1",
                slots=[
                    TemplateSlotSpec(name="scheme", kind="image"),
                    TemplateSlotSpec(name="scheme", kind="text"),
                ],
            )


if __name__ == "__main__":
    unittest.main()
