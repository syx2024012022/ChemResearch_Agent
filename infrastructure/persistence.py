from __future__ import annotations

import json
import threading
from pathlib import Path
from uuid import UUID

from chemresearch_agent.domain.errors import ConcurrentUpdateError, SessionNotFoundError
from chemresearch_agent.domain.models import AgentSession


class JsonSessionRepository:
    """Small MVP repository with optimistic concurrency and atomic file replacement."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, session_id: UUID) -> Path:
        return self._root / f"{session_id}.json"

    def create(self, session: AgentSession) -> AgentSession:
        with self._lock:
            path = self._path(session.session_id)
            if path.exists():
                raise ConcurrentUpdateError(f"session {session.session_id} already exists")
            self._write(path, session)
        return session.model_copy(deep=True)

    def get(self, session_id: UUID) -> AgentSession:
        path = self._path(session_id)
        with self._lock:
            if not path.exists():
                raise SessionNotFoundError(f"session {session_id} does not exist")
            return AgentSession.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, session: AgentSession, *, expected_version: int) -> AgentSession:
        path = self._path(session.session_id)
        with self._lock:
            if not path.exists():
                raise SessionNotFoundError(f"session {session.session_id} does not exist")
            current = AgentSession.model_validate_json(path.read_text(encoding="utf-8"))
            if current.version != expected_version:
                raise ConcurrentUpdateError(
                    f"expected version {expected_version}, found {current.version}"
                )
            self._write(path, session)
        return session.model_copy(deep=True)

    @staticmethod
    def _write(path: Path, session: AgentSession) -> None:
        temporary = path.with_suffix(".tmp")
        payload = json.dumps(session.model_dump(mode="json"), ensure_ascii=False, indent=2)
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)
