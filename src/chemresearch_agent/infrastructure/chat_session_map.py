from __future__ import annotations

import json
import threading
from pathlib import Path
from uuid import UUID


class JsonChatSessionMap:
    """Persistent mapping from a platform conversation id to an internal session UUID.

    The 清小搭 gateway sends a top-level ``sessionId`` per conversation that is a
    platform string, not our internal UUID. This store bridges the two so multi-turn
    interviews and plan approval can resume the same ``AgentSession``.
    """

    def __init__(self, root: Path) -> None:
        self._path = root / "chat_sessions.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self) -> None:
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self._path)

    def get(self, conversation_id: str) -> UUID | None:
        with self._lock:
            value = self._data.get(conversation_id)
        if not value:
            return None
        try:
            return UUID(value)
        except ValueError:
            return None

    def remember(self, conversation_id: str, session_id: UUID) -> None:
        with self._lock:
            self._data[conversation_id] = str(session_id)
            self._write()
