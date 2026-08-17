from __future__ import annotations

import json
import os
from importlib.util import find_spec
from pathlib import Path


def deployment_checks() -> dict[str, dict[str, object]]:
    node = os.getenv("CHEMRESEARCH_NODE")
    modules = os.getenv("CHEMRESEARCH_NODE_MODULES")
    data_root = Path(os.getenv("CHEMRESEARCH_DATA_ROOT", "data")).resolve()
    artifact_tool = Path(modules) / "@oai" / "artifact-tool" / "package.json" if modules else None
    artifact_ready = bool(
        node and Path(node).is_file() and artifact_tool and artifact_tool.is_file()
    )
    fallback_ready = find_spec("pptx") is not None
    return {
        "llm": {
            "ready": bool(os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL")),
            "detail": "OPENAI_API_KEY and OPENAI_MODEL are configured",
        },
        "renderer": {
            "ready": artifact_ready or fallback_ready,
            "detail": (
                "Artifact Tool renderer is ready"
                if artifact_ready
                else "public python-pptx fallback renderer is ready"
                if fallback_ready
                else "no presentation renderer is available"
            ),
        },
        "data_root": {
            "ready": data_root.exists() or data_root.parent.exists(),
            "detail": f"persistent data root: {data_root}",
        },
    }


def main() -> int:
    checks = deployment_checks()
    ready = all(bool(item["ready"]) for item in checks.values())
    print(json.dumps({"ready": ready, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
