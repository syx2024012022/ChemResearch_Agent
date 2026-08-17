from pathlib import Path

from chemresearch_agent.api.preflight import deployment_checks


def test_preflight_reports_missing_runtime_without_exposing_secrets(monkeypatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "CHEMRESEARCH_NODE",
        "CHEMRESEARCH_NODE_MODULES",
    ):
        monkeypatch.delenv(name, raising=False)
    checks = deployment_checks()
    assert checks["llm"]["ready"] is False
    assert checks["renderer"]["ready"] is True
    assert "python-pptx" in str(checks["renderer"]["detail"])
    assert "OPENAI_API_KEY" in str(checks["llm"]["detail"])


def test_preflight_accepts_existing_renderer_paths(monkeypatch, tmp_path: Path) -> None:
    node = tmp_path / "node.exe"
    node.write_bytes(b"")
    modules = tmp_path / "node_modules"
    artifact_tool = modules / "@oai" / "artifact-tool"
    artifact_tool.mkdir(parents=True)
    (artifact_tool / "package.json").write_text('{"name":"@oai/artifact-tool"}')
    monkeypatch.setenv("OPENAI_API_KEY", "not-disclosed")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("CHEMRESEARCH_NODE", str(node))
    monkeypatch.setenv("CHEMRESEARCH_NODE_MODULES", str(modules))
    monkeypatch.setenv("CHEMRESEARCH_DATA_ROOT", str(tmp_path / "data"))
    checks = deployment_checks()
    assert all(bool(item["ready"]) for item in checks.values())
    assert "Artifact Tool" in str(checks["renderer"]["detail"])
