# ChemResearch Agent 比赛提交说明

## 提交内容

- `src/`：Agent、API、Web UI、PDF 解析、Planning、Composer、Renderer 与 Validator。
- `assets/`：内置有机化学组会 PPT 模板及背景资源。
- `benchmarks/`：PDF 解析黄金清单。
- `tests/`：单元测试、契约测试和全链路回归测试。
- `docs/`：架构、部署、接口适配、PPT 规范和开发进度说明。
- `README.md`、`pyproject.toml`、`.env.example`：安装、运行与环境变量示例。

## 有意排除

- `.env`、API Key 和个人凭证。
- `.venv/`、Python/Node 缓存及测试缓存。
- `data/`、`tmp/`、`output/` 中的运行数据和临时产物。
- `projects/` 中 ppt-master 的历史调试工作区。
- `.git/` 本地版本库元数据。

## 上交前检查

1. 根据比赛环境填写环境变量，不要把真实密钥写入提交包。
2. 运行 `pip install -e ".[dev,competition]"` 安装 Python、测试与 OpenAI 依赖。
3. 清小搭普通服务器无需配置私有 Artifact Tool，将自动使用 `python-pptx` 后备 Renderer；若环境提供获授权的 Artifact Tool，再配置 `CHEMRESEARCH_NODE` 与 `CHEMRESEARCH_NODE_MODULES` 以启用高质量首选路径。
4. 运行 `chemresearch-preflight` 检查 LLM、Renderer 与数据目录。
5. 运行 `pytest -q`，当前基线为 42 项通过。
6. 启动 `uvicorn chemresearch_agent.api.asgi:app --host 0.0.0.0 --port 8000`。

比赛平台的附件输入和 `x_soda.attachments` 输出适配说明见 `docs/deployment.md`。
