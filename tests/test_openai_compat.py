from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from chemresearch_agent.api.app import create_app
from test_document_upload_api import ApiRenderer, FakeRemoteFileFetcher, pdf_bytes
from test_paper_discovery_and_chat import FakePaperDiscovery, RichLiteratureSkill


def test_models_endpoint_returns_openai_list() -> None:
    with tempfile.TemporaryDirectory() as directory:
        client = TestClient(create_app(Path(directory)))
        response = client.get("/v1/models")
        assert response.status_code == 200
        payload = response.json()
        assert payload["object"] == "list"
        assert payload["data"][0]["object"] == "model"
        assert payload["data"][0]["id"]


def test_bearer_auth_rejects_wrong_or_missing_credential(monkeypatch) -> None:
    monkeypatch.setenv("CHEMRESEARCH_API_KEY", "sk-secret")
    with tempfile.TemporaryDirectory() as directory:
        client = TestClient(create_app(Path(directory)))
        assert client.get("/v1/models").status_code == 401
        assert client.get("/v1/models", headers={"Authorization": "Bearer wrong"}).status_code == 401
        chat = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer wrong"},
            json={"messages": [{"role": "user", "content": "你好"}]},
        )
        assert chat.status_code == 401


def test_bearer_auth_accepts_correct_credential(monkeypatch) -> None:
    monkeypatch.setenv("CHEMRESEARCH_API_KEY", "sk-secret")
    with tempfile.TemporaryDirectory() as directory:
        client = TestClient(create_app(Path(directory)))
        headers = {"Authorization": "Bearer sk-secret"}
        assert client.get("/v1/models", headers=headers).status_code == 200
        response = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={"messages": [{"role": "user", "content": "你好"}]},
        )
        assert response.status_code == 200
        assert response.json()["choices"][0]["message"]["content"]


def test_session_id_resumes_the_same_conversation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        client = TestClient(
            create_app(
                Path(directory),
                literature_skill=RichLiteratureSkill(),
                presentation_renderer=ApiRenderer(),
                remote_file_fetcher=FakeRemoteFileFetcher(pdf_bytes()),
                paper_discovery=FakePaperDiscovery(),
            )
        )
        conversation = "conv-openai-compat-1"
        first = client.post(
            "/v1/chat/completions",
            json={
                "sessionId": conversation,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "请生成组会 PPT"},
                            {
                                "type": "file",
                                "file": {
                                    "url": "https://oss.example.test/paper.pdf",
                                    "filename": "paper.pdf",
                                },
                            },
                        ],
                    }
                ],
            },
        ).json()
        first_text = first["choices"][0]["message"]["content"]
        assert "主要用途" in first_text

        second = client.post(
            "/v1/chat/completions",
            json={
                "sessionId": conversation,
                "messages": [{"role": "user", "content": "1"}],
            },
        ).json()
        second_text = second["choices"][0]["message"]["content"]
        assert "汇报场合" in second_text
