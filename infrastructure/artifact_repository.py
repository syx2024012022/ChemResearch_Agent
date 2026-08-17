from __future__ import annotations

from pathlib import Path
from uuid import UUID

from chemresearch_agent.domain.errors import ArtifactNotFoundError
from chemresearch_agent.domain.models import PresentationArtifact


class JsonArtifactRepository:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, artifact: PresentationArtifact) -> PresentationArtifact:
        path = self._root / f"{artifact.artifact_id}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)
        return artifact.model_copy(deep=True)

    def get(self, artifact_id: UUID) -> PresentationArtifact:
        path = self._root / f"{artifact_id}.json"
        if not path.exists():
            raise ArtifactNotFoundError(f"artifact {artifact_id} does not exist")
        return PresentationArtifact.model_validate_json(path.read_text(encoding="utf-8"))

    def get_for_session(self, session_id: UUID) -> PresentationArtifact:
        matches = [
            PresentationArtifact.model_validate_json(path.read_text(encoding="utf-8"))
            for path in self._root.glob("*.json")
        ]
        matches = [item for item in matches if item.session_id == session_id]
        if not matches:
            raise ArtifactNotFoundError(f"session {session_id} has no presentation artifact")
        return matches[-1]
