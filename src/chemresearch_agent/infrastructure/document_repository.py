from __future__ import annotations

from pathlib import Path
from uuid import UUID

from chemresearch_agent.domain.errors import DocumentNotFoundError
from chemresearch_agent.domain.models import DocumentParseResult


class JsonDocumentRepository:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, document_id: UUID) -> Path:
        return self._root / f"{document_id}.json"

    def save(self, document: DocumentParseResult) -> DocumentParseResult:
        path = self._path(document.document_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(document.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)
        return document.model_copy(deep=True)

    def get(self, document_id: UUID) -> DocumentParseResult:
        path = self._path(document_id)
        if not path.exists():
            raise DocumentNotFoundError(f"document {document_id} does not exist")
        return DocumentParseResult.model_validate_json(path.read_text(encoding="utf-8"))
