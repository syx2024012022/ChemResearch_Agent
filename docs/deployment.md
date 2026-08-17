# ChemResearch Agent 比赛部署说明

## 必要环境变量

安装比赛运行依赖：

```powershell
python -m pip install -e ".[competition]"
```

复制 `.env.example` 并配置：

- `OPENAI_API_KEY` 与 `OPENAI_MODEL`：Literature Analysis。
- `CHEMRESEARCH_SERVICE_API_KEY`：清小搭调用本服务时的入站密钥。生产/比赛公网部署必须配置；平台填写同一个值，并以 `Authorization: Bearer <key>` 发送。未配置仅适合本机开发。
- `CHEMRESEARCH_NODE`：可选，Artifact Tool 使用的 Node.js 可执行文件绝对路径。
- `CHEMRESEARCH_NODE_MODULES`：可选，包含 `@oai/artifact-tool` 的模块目录。
- `CHEMRESEARCH_DATA_ROOT`：会话、上传、解析结果和 PPTX 的持久化目录。

启动前运行：

```powershell
chemresearch-preflight
```

退出码为 0 才表示完整链路可用。`GET /health` 只表示进程存活；
`GET /health/ready` 会检查 LLM、Renderer 和数据目录，缺项时返回 503 和明确诊断。

当前 Artifact Tool 包来自获授权的 OpenAI/Codex 运行环境，且不会随本仓库分发。
Preflight 会检查 `@oai/artifact-tool/package.json` 是否真实存在；存在时使用高质量
Artifact Tool Renderer，否则自动使用公开可安装的 `python-pptx` 后备 Renderer。

后备 Renderer 保留可编辑文字、图片、透明 callout、Arial/SimHei、speaker notes、
逐页 PNG、montage 与 layout JSON，因此下载和 `x_soda` 输出不依赖 Codex 运行时。

## 启动

```powershell
uvicorn chemresearch_agent.api.asgi:app --host 0.0.0.0 --port 8000 --proxy-headers
```

部署在反向代理后时，代理必须正确传递 `Host`、`X-Forwarded-Proto` 和
`X-Forwarded-Host`。`x_soda.attachments.fileUrl` 与 `previewUrl` 根据当前请求生成，
错误的转发头会导致返回内网 URL 或 HTTP URL。

## 清小搭接口

- OpenAI 兼容入口：`POST /v1/chat/completions`。
- 模型探测：`GET /v1/models`，返回 `chemresearch-agent`，用于清小搭连通性和凭证探测。
- 输入：`POST /v1/sessions/{id}/documents/url`，请求体包含 `url` 与 `filename`。
- 异步生成：`POST /v1/sessions/{id}/presentation/async`。
- 失败重试：`POST /v1/sessions/{id}/presentation/retry`。
- 状态：`GET /v1/sessions/{id}/workflow-status`。
- 附件：`GET /v1/artifacts/{artifact_id}/x-soda`。

`/v1/chat/completions` 可以直接消费清小搭消息中的 `content[].type=file` 和
`file.url`。服务通过隐藏的 `chemresearch-session` 标记从对话历史恢复会话，逐轮完成
需求访谈和规划批准；PPTX 完成后，非流式响应在顶层返回 `x_soda.attachments`，流式
响应只在 stop 帧返回一次。`file.file_id` 暂不解析，应让清小搭按文档推荐发送 URL。

无附件时，用户可以输入 DOI、doi.org URL、直接 HTTPS PDF URL或自然语言检索要求。
OpenAlex 只负责题录和开放获取位置；没有合法开放 PDF 时，服务不会抓取付费墙内容。

当前 `BackgroundTasks` 适合单进程比赛 MVP。若部署为多进程、需要进程重启后继续任务，
必须换成持久化任务队列；不能仅增加 Uvicorn worker 数量。

## 安全边界

- 平台文件输入仅接受 HTTPS URL。
- 阻断私网、回环、链路本地、保留地址和带凭据 URL。
- 关闭环境代理，限制重定向、下载时间和 50 MB 文件大小。
- 下载后仍执行 PDF 文件名、签名和解析校验。
- API Key 只从环境变量读取，不写入仓库或响应。
