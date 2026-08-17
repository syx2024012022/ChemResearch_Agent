from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, File, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from chemresearch_agent.api.chat_adapter import (
    CAPABILITY_MESSAGE,
    WELCOME_MESSAGE,
    ChatCompletionRequest,
    completion_payload,
    find_session_id,
    is_approval,
    is_capability_question,
    is_greeting,
    last_user_input,
    parse_question_answer,
    render_plan,
    render_question,
    with_session,
)
from chemresearch_agent.api.preflight import deployment_checks
from chemresearch_agent.application.document_ingestion import DocumentIngestionService
from chemresearch_agent.application.literature_analysis import LiteratureAnalysisService
from chemresearch_agent.application.orchestrator import AgentOrchestrator
from chemresearch_agent.application.ports import LiteratureSkill, PresentationRenderer
from chemresearch_agent.application.presentation_workflow import (
    PresentationGenerationService,
    PresentationPlanningService,
)
from chemresearch_agent.application.requirements_interview import GuidedRequirementsService
from chemresearch_agent.domain.enums import SessionStatus
from chemresearch_agent.domain.errors import (
    AnalysisUnavailableError,
    ArtifactNotFoundError,
    ConcurrentUpdateError,
    DocumentNotFoundError,
    InvalidTransitionError,
    SessionNotFoundError,
)
from chemresearch_agent.domain.models import (
    AgentSession,
    DocumentParseResult,
    PaperAnalysis,
    PresentationArtifact,
    PresentationRequirements,
    RequirementsQuestion,
    SlidePlan,
)
from chemresearch_agent.infrastructure.artifact_repository import JsonArtifactRepository
from chemresearch_agent.infrastructure.document_repository import JsonDocumentRepository
from chemresearch_agent.infrastructure.file_store import LocalFileStore
from chemresearch_agent.infrastructure.paper_discovery import (
    OpenAlexPaperDiscovery,
    PaperCandidate,
    PaperDiscovery,
)
from chemresearch_agent.infrastructure.persistence import JsonSessionRepository
from chemresearch_agent.infrastructure.remote_file_fetcher import SafeHttpRemoteFileFetcher
from chemresearch_agent.skills.composer import RuleBasedPresentationComposerSkill
from chemresearch_agent.skills.literature import LiteratureAnalysisSkill
from chemresearch_agent.skills.planning import RuleBasedPresentationPlanningSkill
from chemresearch_agent.skills.validation import DeterministicPresentationValidator
from chemresearch_agent.tools.openai_client import openai_client_from_env
from chemresearch_agent.tools.pdf import PyMuPdfParser
from chemresearch_agent.tools.presentation import (
    ArtifactToolPresentationRenderer,
    PythonPptxPresentationRenderer,
)


class DocumentUploadResponse(BaseModel):
    session: AgentSession
    document: DocumentParseResult


class AnalysisResponse(BaseModel):
    session: AgentSession
    analysis: PaperAnalysis


class PlanRevisionRequest(BaseModel):
    reason: str


class PresentationResponse(BaseModel):
    session: AgentSession
    artifact: PresentationArtifact


class RequirementsAnswerRequest(BaseModel):
    step: str
    value: object


class RequirementsInterviewResponse(BaseModel):
    session: AgentSession
    question: RequirementsQuestion | None = None


class SodaAttachment(BaseModel):
    fileUrl: str
    fileName: str
    fileType: str
    mimeType: str
    fileSize: int | None = None
    previewUrl: str | None = None


class SodaExtension(BaseModel):
    attachments: list[SodaAttachment]


class SodaAttachmentResponse(BaseModel):
    x_soda: SodaExtension


class RemoteFileInput(BaseModel):
    url: str
    filename: str


class PaperSearchRequest(BaseModel):
    query: str
    limit: int = 5


class PaperResolveRequest(BaseModel):
    identifier: str


class RemoteFileFetcher(Protocol):
    def fetch(self, url: str, max_bytes: int) -> bytes: ...


class WorkflowStatusResponse(BaseModel):
    session_id: UUID
    status: SessionStatus
    stage: str
    progress: int
    message: str
    retryable: bool = False
    error: dict | None = None
    artifact_id: UUID | None = None
    download_url: str | None = None


class ServiceApiKeyMiddleware(BaseHTTPMiddleware):
    """Require the deployment key on API routes when configured."""

    def __init__(self, app, api_key: str | None) -> None:
        super().__init__(app)
        self.api_key = api_key.strip() if api_key else None

    async def dispatch(self, request: Request, call_next):
        if self.api_key and request.url.path.startswith("/v1/"):
            authorization = request.headers.get("authorization", "")
            supplied = (
                authorization[7:].strip()
                if authorization.casefold().startswith("bearer ")
                else request.headers.get("x-api-key", "").strip()
            )
            if not supplied or not secrets.compare_digest(supplied, self.api_key):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "invalid or missing service API key"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)


def create_app(
    data_root: Path | None = None,
    *,
    literature_skill: LiteratureSkill | None = None,
    presentation_renderer: PresentationRenderer | None = None,
    remote_file_fetcher: RemoteFileFetcher | None = None,
    paper_discovery: PaperDiscovery | None = None,
) -> FastAPI:
    root = data_root or Path(os.getenv("CHEMRESEARCH_DATA_ROOT", "data"))
    orchestrator = AgentOrchestrator(JsonSessionRepository(root / "sessions"))
    documents = JsonDocumentRepository(root / "documents")
    artifacts = JsonArtifactRepository(root / "presentation_artifacts")
    planner = RuleBasedPresentationPlanningSkill()
    composer = RuleBasedPresentationComposerSkill()
    validator = DeterministicPresentationValidator()
    if presentation_renderer is None:
        node = os.getenv("CHEMRESEARCH_NODE")
        modules = os.getenv("CHEMRESEARCH_NODE_MODULES")
        artifact_package = (
            Path(modules) / "@oai" / "artifact-tool" / "package.json" if modules else None
        )
        if node and Path(node).is_file() and artifact_package and artifact_package.is_file():
            presentation_renderer = ArtifactToolPresentationRenderer(Path(node), Path(modules))
        else:
            presentation_renderer = PythonPptxPresentationRenderer()
    if literature_skill is None:
        llm = openai_client_from_env()
        literature_skill = LiteratureAnalysisSkill(llm) if llm else None
    ingestion = DocumentIngestionService(
        orchestrator,
        LocalFileStore(root / "uploads"),
        documents,
        PyMuPdfParser(root / "artifacts" / "documents"),
    )
    remote_file_fetcher = remote_file_fetcher or SafeHttpRemoteFileFetcher()
    paper_discovery = paper_discovery or OpenAlexPaperDiscovery()
    generation_service = PresentationGenerationService(
        orchestrator,
        documents,
        artifacts,
        composer,
        presentation_renderer,
        validator,
        root / "artifacts" / "presentations",
    )
    app = FastAPI(title="ChemResearch Agent API", version="0.1.0")
    app.add_middleware(ServiceApiKeyMiddleware, api_key=os.getenv("CHEMRESEARCH_SERVICE_API_KEY"))
    static_root = Path(__file__).with_name("static")
    app.mount("/ui", StaticFiles(directory=static_root), name="ui")

    @app.get("/", include_in_schema=False)
    def user_interface() -> FileResponse:
        return FileResponse(static_root / "index.html", media_type="text/html")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def readiness() -> JSONResponse:
        checks = deployment_checks()
        ready = all(bool(item["ready"]) for item in checks.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ready" if ready else "degraded", "checks": checks},
        )

    @app.get("/v1/models")
    def models() -> dict:
        """OpenAI-compatible discovery endpoint used by 清小搭 probing."""
        return {
            "object": "list",
            "data": [{"id": "chemresearch-agent", "object": "model", "owned_by": "you"}],
        }

    @app.get("/v1/presentation-requirements/schema")
    def requirements_schema() -> dict:
        schema = PresentationRequirements.model_json_schema()
        schema["recommended_defaults"] = {
            "purpose": "group_meeting",
            "audience_level": "chemistry",
            "language": "en",
            "min_slide_count": 9,
            "max_slide_count": 11,
            "include_speaker_notes": True,
        }
        return schema

    @app.post("/v1/papers/search", response_model=list[PaperCandidate])
    def search_papers(request: PaperSearchRequest) -> list[PaperCandidate]:
        return paper_discovery.search(request.query, request.limit)

    @app.post("/v1/papers/resolve", response_model=PaperCandidate)
    def resolve_paper(request: PaperResolveRequest) -> PaperCandidate:
        return paper_discovery.resolve(request.identifier)

    @app.post("/v1/sessions", response_model=AgentSession, status_code=status.HTTP_201_CREATED)
    def create_session() -> AgentSession:
        return orchestrator.create_session()

    @app.get("/v1/sessions/{session_id}", response_model=AgentSession)
    def get_session(session_id: UUID) -> AgentSession:
        return orchestrator.get_session(session_id)

    @app.post(
        "/v1/sessions/{session_id}/documents",
        response_model=DocumentUploadResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_document(
        session_id: UUID,
        file: Annotated[UploadFile, File()],
    ) -> DocumentUploadResponse:
        content = await file.read(50 * 1024 * 1024 + 1)
        result = ingestion.ingest(session_id, file.filename or "document.pdf", content)
        return DocumentUploadResponse(session=result.session, document=result.document)

    @app.post(
        "/v1/sessions/{session_id}/documents/url",
        response_model=DocumentUploadResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def upload_document_url(session_id: UUID, file: RemoteFileInput) -> DocumentUploadResponse:
        try:
            content = remote_file_fetcher.fetch(file.url, 50 * 1024 * 1024)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("remote file download failed") from exc
        result = ingestion.ingest(session_id, file.filename, content)
        return DocumentUploadResponse(session=result.session, document=result.document)

    @app.get("/v1/documents/{document_id}", response_model=DocumentParseResult)
    def get_document(document_id: UUID) -> DocumentParseResult:
        return documents.get(document_id)

    @app.post("/v1/sessions/{session_id}/analysis", response_model=AnalysisResponse)
    def analyze_document(session_id: UUID) -> AnalysisResponse:
        if literature_skill is None:
            raise AnalysisUnavailableError(
                "literature analysis is not configured; set OPENAI_API_KEY and OPENAI_MODEL"
            )
        result = LiteratureAnalysisService(orchestrator, documents, literature_skill).analyze(
            session_id
        )
        return AnalysisResponse(session=result.session, analysis=result.analysis)

    @app.put("/v1/sessions/{session_id}/requirements", response_model=AgentSession)
    def submit_requirements(
        session_id: UUID,
        requirements: PresentationRequirements,
    ) -> AgentSession:
        return orchestrator.submit_requirements(session_id, requirements)

    @app.post(
        "/v1/sessions/{session_id}/requirements/interview",
        response_model=RequirementsInterviewResponse,
    )
    def start_requirements_interview(session_id: UUID) -> RequirementsInterviewResponse:
        session, question = GuidedRequirementsService(orchestrator).start(session_id)
        return RequirementsInterviewResponse(session=session, question=question)

    @app.post(
        "/v1/sessions/{session_id}/requirements/interview/answer",
        response_model=RequirementsInterviewResponse,
    )
    def answer_requirements_interview(
        session_id: UUID, request: RequirementsAnswerRequest
    ) -> RequirementsInterviewResponse:
        session, question = GuidedRequirementsService(orchestrator).answer(
            session_id, request.step, request.value
        )
        return RequirementsInterviewResponse(session=session, question=question)

    @app.post("/v1/sessions/{session_id}/plan", response_model=AgentSession)
    def create_plan(session_id: UUID) -> AgentSession:
        return PresentationPlanningService(orchestrator, planner).create_plan(session_id)

    @app.get("/v1/sessions/{session_id}/plan", response_model=SlidePlan)
    def get_plan(session_id: UUID) -> SlidePlan:
        plan = orchestrator.get_session(session_id).slide_plan
        if plan is None:
            raise InvalidTransitionError("session has no slide plan")
        return plan

    @app.post("/v1/sessions/{session_id}/plan/revision", response_model=AgentSession)
    def revise_plan(session_id: UUID, request: PlanRevisionRequest) -> AgentSession:
        return orchestrator.request_plan_revision(session_id, request.reason)

    @app.post("/v1/sessions/{session_id}/plan/approval", response_model=AgentSession)
    def approve_plan(session_id: UUID) -> AgentSession:
        return orchestrator.approve_plan(session_id)

    @app.post("/v1/sessions/{session_id}/presentation", response_model=PresentationResponse)
    def generate_presentation(session_id: UUID) -> PresentationResponse:
        session, artifact = generation_service.generate(session_id)
        return PresentationResponse(session=session, artifact=artifact)

    def run_presentation_job(session_id: UUID) -> None:
        try:
            generation_service.generate(session_id)
        except Exception as exc:  # background tasks cannot return an HTTP error
            try:
                orchestrator.record_retryable_failure(
                    session_id, exc, reason="presentation generation failed"
                )
            except Exception:
                # Preserve the original session record if failure recording itself races.
                return

    def attachment_for(artifact: PresentationArtifact, request: Request) -> dict:
        preview_url = (
            str(
                request.url_for(
                    "preview_artifact",
                    artifact_id=str(artifact.artifact_id),
                    slide_number="1",
                )
            )
            if artifact.preview_paths
            else None
        )
        return {
            "fileUrl": str(
                request.url_for("download_artifact", artifact_id=str(artifact.artifact_id))
            ),
            "fileName": "chemresearch-presentation.pptx",
            "fileType": "ppt",
            "mimeType": (
                "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            ),
            "fileSize": Path(artifact.pptx_path).stat().st_size,
            "previewUrl": preview_url,
        }

    def handle_chat(
        chat: ChatCompletionRequest,
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> dict:
        text, files = last_user_input(chat)
        session_id = find_session_id(chat)
        if session_id is None:
            if not files and (not text or is_greeting(text)):
                return completion_payload(WELCOME_MESSAGE)
            if not files and is_capability_question(text):
                return completion_payload(CAPABILITY_MESSAGE)
            if files:
                if len(files) != 1:
                    raise ValueError("一次只能处理一篇论文")
                source = files[0]
                pdf_url, filename = source["url"], source["filename"]
            else:
                try:
                    candidate = paper_discovery.resolve(text)
                except ValueError:
                    candidates = paper_discovery.search(text, 5)
                    if not candidates:
                        return completion_payload("没有找到匹配论文，请提供 DOI 或 PDF 链接。")
                    lines = ["找到以下候选论文。请复制目标论文的 DOI 再发送给我："]
                    for index, item in enumerate(candidates, start=1):
                        access = "开放全文" if item.pdf_url else "仅题录/可能需要上传 PDF"
                        lines.append(
                            f"{index}. {item.title} ({item.year or 'year unknown'})\n"
                            f"   DOI: {item.doi or 'unavailable'} · {access}"
                        )
                    return completion_payload("\n".join(lines))
                if not candidate.pdf_url:
                    return completion_payload(
                        f"已找到论文《{candidate.title}》，但没有合法开放 PDF 地址。"
                        "请通过清小搭上传 PDF，或提供可直接下载的 HTTPS PDF 链接。"
                    )
                pdf_url = candidate.pdf_url
                filename = f"{candidate.doi or 'paper'}.pdf".replace("/", "_")
            session = orchestrator.create_session()
            content = remote_file_fetcher.fetch(pdf_url, 50 * 1024 * 1024)
            ingestion.ingest(session.session_id, filename, content)
            if literature_skill is None:
                raise AnalysisUnavailableError(
                    "literature analysis is not configured; set OPENAI_API_KEY and OPENAI_MODEL"
                )
            result = LiteratureAnalysisService(orchestrator, documents, literature_skill).analyze(
                session.session_id
            )
            _, question = GuidedRequirementsService(orchestrator).start(session.session_id)
            title = result.analysis.metadata.title
            return completion_payload(
                with_session(
                    f"已解析《{title}》。接下来逐步确认汇报要求。\n\n{render_question(question)}",
                    session.session_id,
                )
            )

        session = orchestrator.get_session(session_id)
        if session.status == SessionStatus.NEEDS_REQUIREMENTS:
            service = GuidedRequirementsService(orchestrator)
            if session.requirements_interview is None:
                _, question = service.start(session_id)
            else:
                question = service.question(session)
                answer = parse_question_answer(question, text)
                session, question = service.answer(session_id, question.step, answer)
            if question is not None:
                return completion_payload(with_session(render_question(question), session_id))
            session = PresentationPlanningService(orchestrator, planner).create_plan(session_id)
            return completion_payload(with_session(render_plan(session.slide_plan), session_id))

        if session.status == SessionStatus.PLANNING:
            session = PresentationPlanningService(orchestrator, planner).create_plan(session_id)
            return completion_payload(with_session(render_plan(session.slide_plan), session_id))
        if session.status == SessionStatus.AWAITING_PLAN_APPROVAL:
            if not is_approval(text):
                return completion_payload(
                    with_session("规划尚未批准。请回复“批准”，或在网页端修改规划。", session_id)
                )
            orchestrator.approve_plan(session_id)
            background_tasks.add_task(run_presentation_job, session_id)
            return completion_payload(
                with_session(
                    "规划已批准，正在后台生成和检查 PPTX。稍后回复“查看进度”。",
                    session_id,
                )
            )
        if session.status in {
            SessionStatus.COMPOSING,
            SessionStatus.RENDERING,
            SessionStatus.VALIDATING,
        }:
            status_payload = _workflow_status(session, request)
            return completion_payload(with_session(status_payload.message, session_id))
        if session.status == SessionStatus.COMPLETED:
            artifact = artifacts.get_for_session(session_id)
            return completion_payload(
                with_session("PPTX 已生成并通过自动检查，请下载附件。", session_id),
                attachments=[attachment_for(artifact, request)],
            )
        if session.status == SessionStatus.FAILED_RETRYABLE:
            if "重试" in text:
                orchestrator.prepare_presentation_retry(session_id)
                background_tasks.add_task(run_presentation_job, session_id)
                return completion_payload(with_session("已重新提交生成任务。", session_id))
            return completion_payload(
                with_session("生成失败但可以重试，请回复“重试”。", session_id)
            )
        return completion_payload(with_session(f"当前状态：{session.status.value}", session_id))

    @app.post("/v1/chat/completions")
    def chat_completions(
        chat: ChatCompletionRequest,
        request: Request,
        background_tasks: BackgroundTasks,
    ):
        payload = handle_chat(chat, request, background_tasks)
        if not chat.stream:
            return payload

        def events():
            choice = payload["choices"][0]
            first = {
                "id": payload["id"],
                "object": "chat.completion.chunk",
                "created": payload["created"],
                "model": payload["model"],
                "choices": [{"index": 0, "delta": choice["message"], "finish_reason": None}],
            }
            stop = {
                "id": payload["id"],
                "object": "chat.completion.chunk",
                "created": payload["created"],
                "model": payload["model"],
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": payload["usage"],
            }
            if payload.get("x_soda"):
                stop["x_soda"] = payload["x_soda"]
            yield f"data: {json.dumps(first, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps(stop, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post(
        "/v1/sessions/{session_id}/presentation/async",
        response_model=WorkflowStatusResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def generate_presentation_async(
        session_id: UUID, request: Request, background_tasks: BackgroundTasks
    ) -> WorkflowStatusResponse:
        session = orchestrator.get_session(session_id)
        if session.status != SessionStatus.COMPOSING:
            raise InvalidTransitionError("async generation requires an approved plan")
        background_tasks.add_task(run_presentation_job, session_id)
        return _workflow_status(session, request)

    @app.post(
        "/v1/sessions/{session_id}/presentation/retry",
        response_model=WorkflowStatusResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def retry_presentation(
        session_id: UUID, request: Request, background_tasks: BackgroundTasks
    ) -> WorkflowStatusResponse:
        session = orchestrator.prepare_presentation_retry(session_id)
        background_tasks.add_task(run_presentation_job, session_id)
        return _workflow_status(session, request)

    @app.get(
        "/v1/sessions/{session_id}/workflow-status",
        response_model=WorkflowStatusResponse,
    )
    def workflow_status(session_id: UUID, request: Request) -> WorkflowStatusResponse:
        return _workflow_status(orchestrator.get_session(session_id), request)

    @app.get("/v1/sessions/{session_id}/presentation", response_model=PresentationArtifact)
    def get_presentation(session_id: UUID) -> PresentationArtifact:
        return artifacts.get_for_session(session_id)

    @app.get("/v1/artifacts/{artifact_id}/download")
    def download_artifact(artifact_id: UUID) -> FileResponse:
        artifact = artifacts.get(artifact_id)
        return FileResponse(artifact.pptx_path, filename="chemresearch-presentation.pptx")

    @app.get("/v1/artifacts/{artifact_id}/previews/{slide_number}")
    def preview_artifact(artifact_id: UUID, slide_number: int) -> FileResponse:
        artifact = artifacts.get(artifact_id)
        if slide_number < 1 or slide_number > len(artifact.preview_paths):
            raise ValueError("slide_number is outside the preview range")
        return FileResponse(artifact.preview_paths[slide_number - 1], media_type="image/png")

    @app.get(
        "/v1/artifacts/{artifact_id}/x-soda",
        response_model=SodaAttachmentResponse,
    )
    def soda_attachment(artifact_id: UUID, request: Request) -> SodaAttachmentResponse:
        """Return the URL-only attachment descriptor required by 清小搭."""
        artifact = artifacts.get(artifact_id)
        download_url = str(request.url_for("download_artifact", artifact_id=str(artifact_id)))
        preview_url = (
            str(request.url_for("preview_artifact", artifact_id=str(artifact_id), slide_number="1"))
            if artifact.preview_paths
            else None
        )
        return SodaAttachmentResponse(
            x_soda=SodaExtension(
                attachments=[
                    SodaAttachment(
                        fileUrl=download_url,
                        fileName="chemresearch-presentation.pptx",
                        fileType="ppt",
                        mimeType=(
                            "application/vnd.openxmlformats-officedocument."
                            "presentationml.presentation"
                        ),
                        fileSize=Path(artifact.pptx_path).stat().st_size,
                        previewUrl=preview_url,
                    )
                ]
            )
        )

    @app.exception_handler(SessionNotFoundError)
    @app.exception_handler(DocumentNotFoundError)
    @app.exception_handler(ArtifactNotFoundError)
    async def not_found_handler(
        _, exc: SessionNotFoundError | DocumentNotFoundError | ArtifactNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(InvalidTransitionError)
    async def invalid_transition_handler(_, exc: InvalidTransitionError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ConcurrentUpdateError)
    async def concurrent_update_handler(_, exc: ConcurrentUpdateError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(AnalysisUnavailableError)
    async def unavailable_handler(_, exc: AnalysisUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def validation_handler(_, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    return app


_STATUS_DETAILS: dict[SessionStatus, tuple[str, int, str]] = {
    SessionStatus.CREATED: ("upload", 0, "等待上传论文"),
    SessionStatus.DOCUMENT_UPLOADED: ("upload", 5, "论文已上传"),
    SessionStatus.PARSING: ("parsing", 12, "正在解析 PDF"),
    SessionStatus.ANALYZING: ("analysis", 25, "正在分析论文内容"),
    SessionStatus.NEEDS_REQUIREMENTS: ("requirements", 40, "等待用户确认汇报要求"),
    SessionStatus.PLANNING: ("planning", 52, "正在生成内容规划"),
    SessionStatus.AWAITING_PLAN_APPROVAL: ("approval", 60, "等待用户批准规划"),
    SessionStatus.COMPOSING: ("composing", 70, "正在编排内容与版式"),
    SessionStatus.RENDERING: ("rendering", 82, "正在渲染可编辑 PPTX"),
    SessionStatus.VALIDATING: ("validating", 92, "正在执行内容与视觉检查"),
    SessionStatus.COMPLETED: ("completed", 100, "演示文稿已经完成"),
    SessionStatus.FAILED_RETRYABLE: ("failed", 0, "任务失败，可以修复后重试"),
    SessionStatus.FAILED_FINAL: ("failed", 0, "任务失败，无法自动重试"),
    SessionStatus.CANCELLED: ("cancelled", 0, "任务已取消"),
}


def _workflow_status(session: AgentSession, request: Request) -> WorkflowStatusResponse:
    stage, progress, message = _STATUS_DETAILS[session.status]
    validation_failed = bool(
        session.status == SessionStatus.COMPOSING
        and session.validation_report
        and not session.validation_report.passed
    )
    if validation_failed:
        stage = "validation_failed"
        progress = 100
        message = "PPTX 已生成，但自动检查未通过；请查看预览和诊断后重新生成"
    artifact_id = UUID(session.artifact_ids[-1]) if session.artifact_ids else None
    download_url = (
        str(request.url_for("download_artifact", artifact_id=str(artifact_id)))
        if artifact_id and session.status == SessionStatus.COMPLETED
        else None
    )
    return WorkflowStatusResponse(
        session_id=session.session_id,
        status=session.status,
        stage=stage,
        progress=progress,
        message=message,
        retryable=session.status == SessionStatus.FAILED_RETRYABLE or validation_failed,
        error=session.error,
        artifact_id=artifact_id,
        download_url=download_url,
    )
