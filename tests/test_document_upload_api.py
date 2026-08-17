from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pymupdf
from fastapi.testclient import TestClient

from chemresearch_agent.api.app import create_app
from chemresearch_agent.domain.enums import ClaimBasis
from chemresearch_agent.domain.models import (
    GroundedClaim,
    PaperAnalysis,
    PaperMetadata,
    PresentationArtifact,
)


class ApiLiteratureSkill:
    def analyze(self, document):
        block = document.blocks[0]
        from chemresearch_agent.domain.models import EvidenceRef

        ref = EvidenceRef(
            source_id=block.source_id,
            document_id=document.document_id,
            page_number=block.page_number,
            excerpt=block.text,
        )
        claim = GroundedClaim(text="核心结论", basis=ClaimBasis.EXPLICIT, evidence=[ref])
        return PaperAnalysis(
            document_id=document.document_id,
            metadata=PaperMetadata(title="API chemistry test"),
            research_context=[claim],
            research_gap=[claim],
            innovations=[claim],
        )


class ApiRenderer:
    def render(self, session_id, contents, output_root):
        output_root.mkdir(parents=True, exist_ok=True)
        pptx = output_root / "api-test.pptx"
        pptx.write_bytes(b"PK api test")
        previews = []
        for index, _ in enumerate(contents):
            preview = output_root / f"slide-{index + 1:02d}.png"
            preview.write_bytes(b"png")
            previews.append(str(preview))
        return PresentationArtifact(
            artifact_id=uuid4(),
            session_id=session_id,
            pptx_path=str(pptx),
            preview_paths=previews,
            renderer_version="api-fake",
            input_hash="api-test",
            slide_count=len(contents),
        )


class FakeRemoteFileFetcher:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[tuple[str, int]] = []

    def fetch(self, url: str, max_bytes: int) -> bytes:
        self.calls.append((url, max_bytes))
        return self.payload


def test_configured_service_api_key_protects_v1_routes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        with patch.dict("os.environ", {"CHEMRESEARCH_SERVICE_API_KEY": "test-secret"}):
            client = TestClient(create_app(Path(directory)))
            assert client.get("/health").status_code == 200
            assert client.get("/v1/presentation-requirements/schema").status_code == 401
            assert client.get("/v1/models").status_code == 401
            assert client.get(
                "/v1/presentation-requirements/schema",
                headers={"Authorization": "Bearer wrong"},
            ).status_code == 401
            assert client.get(
                "/v1/presentation-requirements/schema",
                headers={"Authorization": "Bearer test-secret"},
            ).status_code == 200
            models = client.get(
                "/v1/models", headers={"Authorization": "Bearer test-secret"}
            )
            assert models.status_code == 200
            assert models.json()["data"][0]["id"] == "chemresearch-agent"


class FailingOnceRenderer(ApiRenderer):
    def __init__(self) -> None:
        self.calls = 0

    def render(self, session_id, contents, output_root):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary renderer failure")
        return super().render(session_id, contents, output_root)


def pdf_bytes() -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((40, 70), "API upload test")
    page.draw_rect(pymupdf.Rect(45, 180, 555, 420), color=(0, 0, 1), width=2)
    page.insert_textbox(
        pymupdf.Rect(45, 440, 555, 485),
        "Figure 1. A generated figure for the upload endpoint.",
        fontsize=10,
    )
    payload = document.tobytes()
    document.close()
    return payload


class DocumentUploadApiTests(unittest.TestCase):
    def test_button_driven_user_interface_is_served(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(Path(directory)))
            page = client.get("/")
            self.assertEqual(page.status_code, 200)
            self.assertIn("从论文到可编辑组会 PPT", page.text)
            self.assertIn("/ui/app.js", page.text)
            script = client.get("/ui/app.js")
            self.assertEqual(script.status_code, 200)
            self.assertIn("requirements/interview/answer", script.text)
            self.assertIn('state.retryPresentation?"retry":"async"', script.text)
            self.assertIn("presentation/${endpoint}", script.text)
            self.assertIn("workflow-status", script.text)
            self.assertIn("validation_failed", script.text)
            self.assertIn("汇报要求已确认", script.text)

    def test_upload_parses_and_persists_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(Path(directory)))
            created = client.post("/v1/sessions")
            session_id = created.json()["session_id"]
            response = client.post(
                f"/v1/sessions/{session_id}/documents",
                files={"file": ("paper.pdf", pdf_bytes(), "application/pdf")},
            )
            self.assertEqual(response.status_code, 201, response.text)
            payload = response.json()
            self.assertEqual(payload["session"]["status"], "analyzing")
            self.assertEqual(payload["document"]["page_count"], 1)
            self.assertEqual(len(payload["document"]["figures"]), 1)
            document_id = payload["document"]["document_id"]
            restored = client.get(f"/v1/documents/{document_id}")
            self.assertEqual(restored.status_code, 200)
            self.assertEqual(restored.json()["file_name"], "paper.pdf")

    def test_rejects_non_pdf_without_advancing_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(Path(directory)))
            session_id = client.post("/v1/sessions").json()["session_id"]
            response = client.post(
                f"/v1/sessions/{session_id}/documents",
                files={"file": ("notes.txt", b"not a pdf", "text/plain")},
            )
            self.assertEqual(response.status_code, 422)
            session = client.get(f"/v1/sessions/{session_id}").json()
            self.assertEqual(session["status"], "created")

    def test_accepts_platform_file_url_through_bounded_fetcher(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fetcher = FakeRemoteFileFetcher(pdf_bytes())
            client = TestClient(create_app(Path(directory), remote_file_fetcher=fetcher))
            session_id = client.post("/v1/sessions").json()["session_id"]
            response = client.post(
                f"/v1/sessions/{session_id}/documents/url",
                json={
                    "url": "https://files.example.test/paper.pdf",
                    "filename": "paper.pdf",
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["document"]["page_count"], 1)
            self.assertEqual(fetcher.calls[0][0], "https://files.example.test/paper.pdf")
            self.assertEqual(fetcher.calls[0][1], 50 * 1024 * 1024)

    def test_full_api_workflow_reaches_downloadable_presentation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(
                create_app(
                    Path(directory),
                    literature_skill=ApiLiteratureSkill(),
                    presentation_renderer=ApiRenderer(),
                )
            )
            schema = client.get("/v1/presentation-requirements/schema")
            self.assertEqual(schema.status_code, 200)
            session_id = client.post("/v1/sessions").json()["session_id"]
            upload = client.post(
                f"/v1/sessions/{session_id}/documents",
                files={"file": ("paper.pdf", pdf_bytes(), "application/pdf")},
            )
            self.assertEqual(upload.status_code, 201)
            self.assertEqual(client.post(f"/v1/sessions/{session_id}/analysis").status_code, 200)
            requirements = client.put(
                f"/v1/sessions/{session_id}/requirements",
                json={
                    "purpose": "group_meeting",
                    "duration_minutes": 10,
                    "target_slide_count": 5,
                    "title_include_toc_graphic": False,
                    "require_visual_each_slide": False,
                },
            )
            self.assertEqual(requirements.status_code, 200)
            self.assertEqual(client.post(f"/v1/sessions/{session_id}/plan").status_code, 200)
            approval = client.post(f"/v1/sessions/{session_id}/plan/approval")
            self.assertEqual(approval.json()["status"], "composing")
            queued = client.post(f"/v1/sessions/{session_id}/presentation/async")
            self.assertEqual(queued.status_code, 202, queued.text)
            self.assertEqual(queued.json()["stage"], "composing")
            workflow = client.get(f"/v1/sessions/{session_id}/workflow-status")
            self.assertEqual(workflow.status_code, 200)
            self.assertEqual(workflow.json()["status"], "completed")
            self.assertEqual(workflow.json()["progress"], 100)
            artifact_id = workflow.json()["artifact_id"]
            self.assertTrue(workflow.json()["download_url"].endswith(f"/{artifact_id}/download"))
            self.assertEqual(client.get(f"/v1/artifacts/{artifact_id}/download").status_code, 200)
            self.assertEqual(client.get(f"/v1/artifacts/{artifact_id}/previews/1").status_code, 200)
            soda = client.get(f"/v1/artifacts/{artifact_id}/x-soda")
            self.assertEqual(soda.status_code, 200)
            attachment = soda.json()["x_soda"]["attachments"][0]
            self.assertEqual(attachment["fileType"], "ppt")
            self.assertEqual(
                attachment["mimeType"],
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
            self.assertTrue(attachment["fileUrl"].endswith(f"/{artifact_id}/download"))
            self.assertTrue(attachment["previewUrl"].endswith(f"/{artifact_id}/previews/1"))

    def test_default_app_uses_public_renderer_without_private_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                "os.environ",
                {"CHEMRESEARCH_NODE": "", "CHEMRESEARCH_NODE_MODULES": ""},
            ):
                client = TestClient(
                    create_app(Path(directory), literature_skill=ApiLiteratureSkill())
                )
            session_id = client.post("/v1/sessions").json()["session_id"]
            client.post(
                f"/v1/sessions/{session_id}/documents",
                files={"file": ("paper.pdf", pdf_bytes(), "application/pdf")},
            )
            client.post(f"/v1/sessions/{session_id}/analysis")
            client.put(
                f"/v1/sessions/{session_id}/requirements",
                json={
                    "purpose": "group_meeting",
                    "target_slide_count": 3,
                    "title_include_toc_graphic": False,
                    "require_visual_each_slide": False,
                    "prefer_visual_dominance": False,
                },
            )
            client.post(f"/v1/sessions/{session_id}/plan")
            client.post(f"/v1/sessions/{session_id}/plan/approval")
            generated = client.post(f"/v1/sessions/{session_id}/presentation")
            self.assertEqual(generated.status_code, 200, generated.text)
            artifact = generated.json()["artifact"]
            self.assertEqual(artifact["renderer_version"], "python-pptx-1.0")
            self.assertTrue(Path(artifact["pptx_path"]).is_file())

    def test_async_generation_failure_can_be_retried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            renderer = FailingOnceRenderer()
            client = TestClient(
                create_app(
                    Path(directory),
                    literature_skill=ApiLiteratureSkill(),
                    presentation_renderer=renderer,
                )
            )
            session_id = client.post("/v1/sessions").json()["session_id"]
            client.post(
                f"/v1/sessions/{session_id}/documents",
                files={"file": ("paper.pdf", pdf_bytes(), "application/pdf")},
            )
            client.post(f"/v1/sessions/{session_id}/analysis")
            client.put(
                f"/v1/sessions/{session_id}/requirements",
                json={
                    "purpose": "group_meeting",
                    "target_slide_count": 5,
                    "title_include_toc_graphic": False,
                    "require_visual_each_slide": False,
                },
            )
            client.post(f"/v1/sessions/{session_id}/plan")
            client.post(f"/v1/sessions/{session_id}/plan/approval")
            first = client.post(f"/v1/sessions/{session_id}/presentation/async")
            self.assertEqual(first.status_code, 202)
            failed = client.get(f"/v1/sessions/{session_id}/workflow-status").json()
            self.assertEqual(failed["status"], "failed_retryable")
            self.assertTrue(failed["retryable"])
            self.assertEqual(failed["error"]["message"], "temporary renderer failure")
            retried = client.post(f"/v1/sessions/{session_id}/presentation/retry")
            self.assertEqual(retried.status_code, 202)
            completed = client.get(f"/v1/sessions/{session_id}/workflow-status").json()
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(renderer.calls, 2)


if __name__ == "__main__":
    unittest.main()
