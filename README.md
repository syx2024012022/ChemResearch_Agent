# ChemResearch Agent

面向有机化学文献阅读和组会汇报生成的、基于证据的交互式 Agent。

当前版本已包含：

- 核心领域数据契约
- 显式工作流状态机及用户确认门禁
- 带乐观并发控制的会话持久化
- 可追溯证据的 Literature Analysis Skill、PDF Parser、LLM 和规划器端口
- FastAPI 基础入口
- 核心规则单元测试

真实 PDF 解析和可编辑 PPTX 渲染已经接入。模型调用 Adapter 已实现，需配置
API Key 后运行。

当前已加入 PDF 解析器评测框架。默认运行轻量的 PyMuPDF 与
pdfplumber/pypdf；Docling、GROBID REST 和 MinerU Cloud 为可选 Adapter。
云端解析默认关闭，必须通过环境变量显式授权。

生产解析流程已经接入 PyMuPDF：上传 PDF 后提取带页码和坐标的文本块，识别
Figure 图注，裁切科研图，并建立正文引用到 Figure 的关联。

## 本地开发

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,competition]"
pytest
uvicorn chemresearch_agent.api.asgi:app --reload
```

运行首个解析器基准：

```powershell
chemresearch-parser-benchmark `
  "C:\path\to\n-boryl-pyridyl-anion-chemistry.pdf"
```

如需云端候选：GROBID 使用 `GROBID_URL`；MinerU 必须设置
`MINERU_ALLOW_UPLOAD=1`，精准模式额外使用 `MINERU_TOKEN`。

服务启动后可访问：

- `GET /`：按钮式端到端操作界面
- `GET /health`
- `POST /v1/chat/completions`：清小搭/OpenAI 兼容多轮入口，支持 `file.url` 与最终 `x_soda`
- `POST /v1/papers/search`：按自然语言检索论文题录与开放全文位置
- `POST /v1/papers/resolve`：解析 DOI、doi.org URL 或直接 HTTPS PDF URL
- `POST /v1/sessions`
- `GET /v1/sessions/{session_id}`
- `POST /v1/sessions/{session_id}/documents`
- `POST /v1/sessions/{session_id}/documents/url`：接收清小搭 `file.url`
- `GET /v1/documents/{document_id}`
- `POST /v1/sessions/{session_id}/analysis`
- `PUT /v1/sessions/{session_id}/requirements`
- `POST /v1/sessions/{session_id}/requirements/interview`
- `POST /v1/sessions/{session_id}/requirements/interview/answer`
- `POST /v1/sessions/{session_id}/plan/approval`
- `GET /v1/presentation-requirements/schema`
- `POST /v1/sessions/{session_id}/plan`
- `GET /v1/sessions/{session_id}/plan`
- `POST /v1/sessions/{session_id}/plan/revision`
- `POST /v1/sessions/{session_id}/presentation`
- `POST /v1/sessions/{session_id}/presentation/async`：异步提交生成任务
- `POST /v1/sessions/{session_id}/presentation/retry`：重试可恢复的生成失败
- `GET /v1/sessions/{session_id}/workflow-status`：查询阶段、进度和错误
- `GET /v1/sessions/{session_id}/presentation`
- `GET /v1/artifacts/{artifact_id}/download`
- `GET /v1/artifacts/{artifact_id}/previews/{slide_number}`
- `GET /v1/artifacts/{artifact_id}/x-soda`：清小搭 URL-only 附件描述

清小搭 URL 文件输入仅接受 HTTPS，并执行 50 MB 上限、超时、有限重定向和
私网/回环/链路本地地址阻断；文件下载后仍会经过原有 PDF 类型和内容校验。

用户也可以直接发送 DOI、doi.org URL、HTTPS PDF 地址或自然语言论文主题。

当前主要针对有机化学论文优化。DOI/主题检索只使用 OpenAlex 明确提供的合法开放
PDF，不绕过付费墙；扫描件 OCR、超长论文自动分块、验证失败后的全自动修订循环和
多进程高并发部署暂不属于本版能力。完整说明见
[`docs/paper-discovery-and-xiaoda.md`](docs/paper-discovery-and-xiaoda.md)。
题录检索使用 OpenAlex；只有其明确给出的开放 PDF 地址才会进入自动下载，付费墙论文
只返回题录并要求用户通过清小搭上传 PDF，不绕过访问权限。

详细边界和依赖关系见 `docs/architecture.md`，数据约束见
`docs/data-contracts.md`，比赛部署见 `docs/deployment.md`。

论文分析采用结构化输出，并在程序内把模型返回的 `source_id` 解析为页码和原文摘录；
未知来源编号会被拒绝。模型依赖为可选安装：

```powershell
python -m pip install -e ".[llm-openai]"
$env:OPENAI_API_KEY="..."
$env:OPENAI_MODEL="gpt-5.6"
```

未配置密钥时，PDF 解析仍可使用，analysis 接口会返回 HTTP 503，不会生成伪结果。

Planning 与 Composer 首版提供确定性实现，因此无需模型也可测试后半段流程。PPTX
Renderer 会优先使用 `@oai/artifact-tool`；未配置私有运行时时自动使用公开依赖
`python-pptx` 后备 Renderer。Artifact Tool 可选配置如下：

```powershell
$env:CHEMRESEARCH_NODE="C:\path\to\node.exe"
$env:CHEMRESEARCH_NODE_MODULES="C:\path\to\node_modules"
```

配置 Artifact Tool 时，`CHEMRESEARCH_NODE_MODULES` 指向的目录必须实际包含
`@oai/artifact-tool/package.json`。该包来自获授权的 OpenAI/Codex Artifact Tool
运行环境，不随本仓库分发。清小搭等普通服务器无需该包：应用会自动使用
`PythonPptxPresentationRenderer`，继续生成可编辑 PPTX、speaker notes、逐页预览、
montage 和 layout JSON。

完整门禁为：用户提交需求后才能规划，规划获得批准后才能生成演示文稿，验证通过后
会话才进入 `completed`。验证覆盖来源 notes、规划/页面对应、模板容量、素材存在性、
画布越界和标题换行。
