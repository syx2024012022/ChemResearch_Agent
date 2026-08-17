from __future__ import annotations

import re
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from test_document_upload_api import ApiRenderer, FakeRemoteFileFetcher, pdf_bytes

from chemresearch_agent.api.app import create_app
from chemresearch_agent.api.chat_adapter import is_approval
from chemresearch_agent.domain.enums import ClaimBasis, EvidenceKind
from chemresearch_agent.domain.models import (
    EvidenceRef,
    GroundedClaim,
    PaperAnalysis,
    PaperMetadata,
)
from chemresearch_agent.infrastructure.paper_discovery import (
    PaperCandidate,
    extract_doi,
)


class FakePaperDiscovery:
    def search(self, query: str, limit: int = 5):
        return [
            PaperCandidate(
                title=f"Result for {query}",
                year=2026,
                doi="10.1000/test",
                pdf_url="https://papers.example.test/paper.pdf",
                is_open_access=True,
            )
        ][:limit]

    def resolve(self, identifier: str):
        if extract_doi(identifier) or identifier.endswith(".pdf"):
            return PaperCandidate(
                title="Resolved paper",
                doi=extract_doi(identifier),
                pdf_url="https://papers.example.test/paper.pdf",
                is_open_access=True,
            )
        raise ValueError("not an identifier")


class RichLiteratureSkill:
    def analyze(self, document):
        figure = document.figures[0]
        ref = EvidenceRef(
            source_id=figure.caption_source_id,
            document_id=document.document_id,
            page_number=figure.page_number,
            kind=EvidenceKind.FIGURE,
            excerpt=figure.caption,
            label=figure.label,
        )
        claims = [
            GroundedClaim(
                text=f"Evidence-grounded finding {index}",
                basis=ClaimBasis.EXPLICIT,
                evidence=[ref],
            )
            for index in range(1, 8)
        ]
        return PaperAnalysis(
            document_id=document.document_id,
            metadata=PaperMetadata(title="Chat chemistry paper"),
            research_context=[claims[0]],
            research_gap=[claims[1]],
            innovations=claims[2:],
            key_results=[claims[-1]],
        )


def _chat(client: TestClient, messages: list[dict], *, stream: bool = False):
    response = client.post(
        "/v1/chat/completions",
        json={"model": "chemresearch-agent", "messages": messages, "stream": stream},
    )
    assert response.status_code == 200, response.text
    return response


def test_extract_doi_from_plain_text_and_url() -> None:
    assert extract_doi("10.1021/acs.orglett.6c00911") == "10.1021/acs.orglett.6c00911"
    assert extract_doi("https://doi.org/10.1002/anie.202600001") == "10.1002/anie.202600001"
    assert is_approval("批准，开始生成")
    assert not is_approval("不批准，先修改")


def test_natural_language_search_returns_candidates() -> None:
    with tempfile.TemporaryDirectory() as directory:
        client = TestClient(create_app(Path(directory), paper_discovery=FakePaperDiscovery()))
        response = _chat(
            client,
            [{"role": "user", "content": "recent palladium migration organosilicon chemistry"}],
        )
        text = response.json()["choices"][0]["message"]["content"]
        assert "Result for" in text
        assert "10.1000/test" in text


def test_chat_explains_current_capabilities_without_starting_search() -> None:
    with tempfile.TemporaryDirectory() as directory:
        client = TestClient(create_app(Path(directory), paper_discovery=FakePaperDiscovery()))
        response = _chat(client, [{"role": "user", "content": "你能做什么、有哪些限制？"}])
        text = response.json()["choices"][0]["message"]["content"]
        assert "解析 DOI" in text
        assert "纯扫描件" in text
        assert "不绕过出版商付费墙" in text
        assert "Result for" not in text


def test_chat_greeting_returns_onboarding_instead_of_paper_search() -> None:
    with tempfile.TemporaryDirectory() as directory:
        client = TestClient(create_app(Path(directory), paper_discovery=FakePaperDiscovery()))
        response = _chat(client, [{"role": "user", "content": "你好"}])
        text = response.json()["choices"][0]["message"]["content"]
        assert "我是 ChemDeck" in text
        assert "发送 DOI" in text
        assert "Result for" not in text


def test_file_url_chat_runs_interview_plan_generation_and_x_soda() -> None:
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
        messages = [
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
        ]
        first = _chat(client, messages).json()
        assistant = first["choices"][0]["message"]["content"]
        assert "chemresearch-session:" in assistant
        assert "主要用途" in assistant
        messages.append({"role": "assistant", "content": assistant})

        answers = [
            "1",
            "有机化学课题组研究生和老师",
            "1",
            "全部",
            "是",
            "图多字少、版面较满、突出反应和机理",
            "确认",
            "2",
        ]
        for answer in answers:
            messages.append({"role": "user", "content": answer})
            payload = _chat(client, messages).json()
            assistant = payload["choices"][0]["message"]["content"]
            messages.append({"role": "assistant", "content": assistant})
        assert "已生成" in assistant and "页规划" in assistant

        messages.append({"role": "user", "content": "批准"})
        approved = _chat(client, messages).json()
        messages.append(
            {"role": "assistant", "content": approved["choices"][0]["message"]["content"]}
        )
        messages.append({"role": "user", "content": "查看进度"})
        completed = _chat(client, messages).json()
        session_id = re.search(r"chemresearch-session:([0-9a-f-]{36})", assistant).group(1)
        session = client.get(f"/v1/sessions/{session_id}").json()
        assert "x_soda" in completed, {"completion": completed, "session": session}
        assert completed["x_soda"]["attachments"][0]["fileType"] == "ppt"
        assert completed["x_soda"]["attachments"][0]["fileUrl"].endswith("/download")
        messages.append(
            {"role": "assistant", "content": completed["choices"][0]["message"]["content"]}
        )
        messages.append({"role": "user", "content": "再次发送下载附件"})
        streamed = _chat(client, messages, stream=True).text
        assert streamed.count('"x_soda"') == 1
        stop_line = next(line for line in streamed.splitlines() if '"x_soda"' in line)
        assert '"finish_reason": "stop"' in stop_line


def test_streaming_response_places_x_soda_only_on_stop_frame() -> None:
    with tempfile.TemporaryDirectory() as directory:
        client = TestClient(create_app(Path(directory), paper_discovery=FakePaperDiscovery()))
        response = _chat(
            client,
            [{"role": "user", "content": "photoredox pyridine borylation"}],
            stream=True,
        )
        assert "data: [DONE]" in response.text
        assert "chat.completion.chunk" in response.text
