from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_importing_app_factory_has_no_runtime_directory_side_effect(tmp_path: Path) -> None:
    source_root = Path(__file__).resolve().parents[1] / "src"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source_root)
    result = subprocess.run(
        [sys.executable, "-c", "from chemresearch_agent.api.app import create_app"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "data").exists()


def test_asgi_entrypoint_loads_and_serves_health(tmp_path: Path) -> None:
    source_root = Path(__file__).resolve().parents[1] / "src"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source_root)
    environment["CHEMRESEARCH_DATA_ROOT"] = str(tmp_path / "runtime-data")
    code = (
        "from fastapi.testclient import TestClient; "
        "from chemresearch_agent.api.asgi import app; "
        "response=TestClient(app).get('/health'); "
        "assert response.status_code == 200; "
        "assert response.json() == {'status': 'ok'}"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "runtime-data" / "sessions").is_dir()
