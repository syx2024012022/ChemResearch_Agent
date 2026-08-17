from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from chemresearch_agent.domain.models import AgentSession, DocumentParseResult

from .orchestrator import AgentOrchestrator
from .ports import DocumentRepository, FileStore, PdfParser


@dataclass(frozen=True)
class DocumentIngestionResult:
    session: AgentSession
    document: DocumentParseResult


class DocumentIngestionService:
    def __init__(
        self,
        orchestrator: AgentOrchestrator,
        files: FileStore,
        documents: DocumentRepository,
        parser: PdfParser,
        *,
        max_file_size: int = 50 * 1024 * 1024,
    ) -> None:
        self._orchestrator = orchestrator
        self._files = files
        self._documents = documents
        self._parser = parser
        self._max_file_size = max_file_size

    def ingest(self, session_id: UUID, file_name: str, content: bytes) -> DocumentIngestionResult:
        self._validate_pdf(file_name, content)
        document_id, path, _ = self._files.save_upload(file_name, content)
        self._orchestrator.attach_document(session_id, document_id)
        self._orchestrator.start_parsing(session_id)
        try:
            document = self._parser.parse(document_id, path)
            self._documents.save(document)
        except Exception as exc:
            self._orchestrator.record_retryable_failure(session_id, exc)
            raise
        session = self._orchestrator.finish_parsing(session_id)
        return DocumentIngestionResult(session=session, document=document)

    def _validate_pdf(self, file_name: str, content: bytes) -> None:
        if not file_name.lower().endswith(".pdf"):
            raise ValueError("only PDF files are accepted")
        if not content:
            raise ValueError("uploaded file is empty")
        if len(content) > self._max_file_size:
            raise ValueError(f"PDF exceeds the {self._max_file_size // (1024 * 1024)} MB limit")
        if not content.startswith(b"%PDF-"):
            raise ValueError("file content is not a valid PDF")
