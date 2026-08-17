from __future__ import annotations

import hashlib
import re
from pathlib import Path
from uuid import UUID, uuid4


class LocalFileStore:
    def __init__(self, upload_root: Path) -> None:
        self._upload_root = upload_root
        self._upload_root.mkdir(parents=True, exist_ok=True)

    def save_upload(self, file_name: str, content: bytes) -> tuple[UUID, Path, str]:
        if not content:
            raise ValueError("uploaded file is empty")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file_name).name).strip("._")
        safe_name = safe_name or "document.pdf"
        document_id = uuid4()
        digest = hashlib.sha256(content).hexdigest()
        destination = self._upload_root / str(document_id) / safe_name
        destination.parent.mkdir(parents=True, exist_ok=False)
        destination.write_bytes(content)
        return document_id, destination, digest
