from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import UUID

from chemresearch_agent.domain.models import PresentationArtifact, SlideContent
from chemresearch_agent.skills.templates import BuiltinTemplateRegistry


class ArtifactToolPresentationRenderer:
    version = "artifact-tool-0.1"

    def __init__(self, node_executable: Path, node_modules: Path) -> None:
        self._node = node_executable
        self._node_modules = node_modules
        self._script = Path(__file__).with_name("renderer.mjs")
        self._templates = BuiltinTemplateRegistry()
        template_root = (
            Path(__file__).resolve().parents[4] / "assets" / "templates" / "chem_group_standard"
        )
        self._title_background = template_root / "slide-1.png"
        self._content_background = template_root / "slide-2.png"

    def render(
        self, session_id: UUID, contents: list[SlideContent], output_root: Path
    ) -> PresentationArtifact:
        payload = {
            "template_backgrounds": {
                "title": str(self._title_background.resolve()),
                "content": str(self._content_background.resolve()),
            },
            "contents": [
                {
                    **content.model_dump(mode="json"),
                    "layout": self._templates.get(content.template_id).layout,
                }
                for content in contents
            ],
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(f"{session_id}:{serialized}".encode()).hexdigest()
        artifact_id = UUID(digest[:32])
        output_dir = output_root / str(artifact_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        input_path = output_dir / "render-input.json"
        input_path.write_text(serialized, encoding="utf-8")
        runtime_script = output_dir / "renderer.mjs"
        shutil.copy2(self._script, runtime_script)
        module_link = output_dir / "node_modules"
        if not module_link.exists():
            try:
                os.symlink(self._node_modules, module_link, target_is_directory=True)
            except OSError:
                if os.name != "nt":
                    raise
                subprocess.run(
                    [
                        "cmd",
                        "/c",
                        "mklink",
                        "/J",
                        str(module_link.resolve()),
                        str(self._node_modules.resolve()),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
        environment = os.environ.copy()
        environment["NODE_PATH"] = str(self._node_modules)
        process = subprocess.run(
            [str(self._node), str(runtime_script), str(input_path), str(output_dir)],
            check=False,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
        )
        required_outputs = [output_dir / "presentation.pptx", output_dir / "montage.webp"]
        if process.returncode and not all(path.exists() for path in required_outputs):
            raise RuntimeError(
                f"Artifact Tool rendering failed ({process.returncode}): {process.stderr.strip()}"
            )
        previews = sorted(str(path.resolve()) for path in output_dir.glob("slide-*.png"))
        layouts = sorted(str(path.resolve()) for path in output_dir.glob("slide-*.layout.json"))
        return PresentationArtifact(
            artifact_id=artifact_id,
            session_id=session_id,
            pptx_path=str((output_dir / "presentation.pptx").resolve()),
            preview_paths=previews,
            layout_paths=layouts,
            montage_path=str((output_dir / "montage.webp").resolve()),
            render_log=[
                f"node_exit_code={process.returncode}",
                f"previews={len(previews)}",
                f"layouts={len(layouts)}",
            ],
            renderer_version=self.version,
            input_hash=digest,
            slide_count=len(contents),
        )
