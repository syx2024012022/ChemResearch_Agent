# 论文发现与清小搭对接

## 支持的论文入口

1. 清小搭 `file.url`：平台把用户上传的 PDF 放到 OSS，本服务安全下载。
2. 直接 HTTPS PDF URL：经过与上传文件相同的 SSRF、重定向、大小和 PDF 校验。
3. DOI 或 doi.org URL：通过 OpenAlex 解析题录及合法开放全文位置。
4. 自然语言主题：返回最多五个候选题录、DOI 和开放全文状态，再由用户确认。

任何没有明确开放 PDF 地址的论文都不会自动下载。服务会展示题录并要求用户上传合法
PDF，不尝试绕过出版社登录、机构授权或付费墙。

本地演示网页也提供“DOI 或 PDF 直链”输入框：DOI 先通过 OpenAlex 解析，仅在存在
合法开放全文时下载；否则明确提示用户上传 PDF。

## 对用户公开的能力边界

- 当前主要针对有机化学论文优化，其他学科效果不保证。
- 普通出版网页和任意 HTML 页面不能可靠转换成论文全文。
- 清小搭 `file_id` 暂不支持，应按平台接口优先发送 `file.url`。
- 纯扫描件缺少完整 OCR 支持；超过约 12 万字符的论文尚未自动分块分析。
- Literature Analysis 需要模型 API Key，未配置时明确失败，不生成伪内容。
- 生成失败支持手动重试，但尚无“诊断—自动修订—再次验证”的自治循环。
- 后备渲染器的 PNG 预览不是 PowerPoint 原生截图，跨环境显示可能略有差异。
- JSON 持久化和进程内后台任务面向比赛演示与单实例部署，不适合高并发生产服务。

## 清小搭多轮流程

```text
file.url / DOI / PDF URL
  -> PDF 解析与 Literature Analysis
  -> 逐步需求访谈
  -> SlidePlan 展示与用户批准
  -> 后台 Composer / Renderer / Validator
  -> 用户查看进度
  -> x_soda.attachments 返回 PPTX
```

会话 ID 写入 assistant 文本末尾的 HTML 注释：

```html
<!-- chemresearch-session:UUID -->
```

清小搭在后续请求中携带对话历史时，Adapter 可据此恢复服务端 Session。该标记不包含
密钥或论文内容。若平台不回传 assistant 历史，需要平台额外提供 conversation ID，
再增加 conversation-to-session 映射。

## 流式约束

- 普通文本放在 delta chunk。
- `x_soda.attachments` 只放在 `finish_reason=stop` 的最后一帧。
- 随后发送 `data: [DONE]`。
- 附件 URL 必须在响应后短时间内可由清小搭公网访问，以便平台转存。
