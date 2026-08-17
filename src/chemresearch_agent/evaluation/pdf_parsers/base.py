from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import shutil
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path
from uuid import UUID

from .models import ParserRunResult, ParserRunStatus


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def normalize_text(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\u2011", "-").replace("\u2212", "-")
    return re.sub(r"\s+", " ", text).strip()


class PdfParserAdapter(ABC):
    name: str
    package_name: str | None = None
    deployment_points: float = 0

    def run(self, document_id: UUID, pdf_path: Path, output_root: Path) -> ParserRunResult:
        started = time.perf_counter()
        version = package_version(self.package_name) if self.package_name else None
        output_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{self.name}-", dir=output_root))
        destination = output_root / self.name
        try:
            result = self.parse(document_id, pdf_path, temporary)
            result.parser_name = self.name
            result.parser_version = version
            result.deployment_points = self.deployment_points
            result.elapsed_seconds = time.perf_counter() - started
            if destination.exists():
                shutil.rmtree(destination)
            temporary.replace(destination)

            def relocate(value: str) -> str:
                path = Path(value)
                return (
                    str(destination / path.relative_to(temporary))
                    if path.is_relative_to(temporary)
                    else value
                )

            result.artifacts = {key: relocate(value) for key, value in result.artifacts.items()}
            if result.document is not None:
                blocks = [
                    block.model_copy(
                        update={"asset_path": relocate(block.asset_path)}
                        if block.asset_path
                        else {}
                    )
                    for block in result.document.blocks
                ]
                figures = [
                    figure.model_copy(update={"asset_path": relocate(figure.asset_path)})
                    for figure in result.document.figures
                ]
                result.document = result.document.model_copy(
                    update={"blocks": blocks, "figures": figures}
                )
                normalized_json = result.artifacts.get("json")
                if normalized_json and Path(normalized_json).is_file():
                    Path(normalized_json).write_text(
                        json.dumps(
                            result.document.model_dump(mode="json"),
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
            return result
        except ModuleNotFoundError as exc:
            shutil.rmtree(temporary, ignore_errors=True)
            return ParserRunResult(
                parser_name=self.name,
                parser_version=version,
                status=ParserRunStatus.SKIPPED,
                elapsed_seconds=time.perf_counter() - started,
                deployment_points=self.deployment_points,
                warnings=[f"missing optional dependency: {exc.name}"],
            )
        except Exception as exc:  # adapters must return failures, not half-written output
            shutil.rmtree(temporary, ignore_errors=True)
            return ParserRunResult(
                parser_name=self.name,
                parser_version=version,
                status=ParserRunStatus.FAILED,
                elapsed_seconds=time.perf_counter() - started,
                deployment_points=self.deployment_points,
                errors=[f"{type(exc).__name__}: {exc}"],
            )

    @abstractmethod
    def parse(self, document_id: UUID, pdf_path: Path, work_dir: Path) -> ParserRunResult:
        raise NotImplementedError
