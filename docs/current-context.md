# ChemResearch Agent 精简交接上下文

更新时间：2026-08-16

## 项目目标与现状

构建面向有机化学组会的论文到 PPT Agent。当前完整链路已经跑通：

`PDF 解析 → Literature Analysis → 分步需求访谈 → Planning → 用户批准 → Composer → 可编辑 PPTX → 自动验证`

- PDF 主解析器：PyMuPDF。
- PPTX Renderer：`@oai/artifact-tool`。
- 默认模板：`assets/templates/chem_group_standard.pptx`。
- 默认可见语言：英文；英文 Arial，中文 SimHei。
- 当前测试：54 项通过。
- 详细长期规范：`docs/presentation-standard.md`。
- 版式截图总结：`docs/presentation-layout-reference.md`。

## 已确认的交互逻辑

- Agent 应逐步询问用途、场合、听众、语言、页数范围、讲稿和特殊要求。
- 不强制询问汇报时间；页数采用“约 10 页”等柔性范围。
- 重点由 Agent 根据论文内容提出，再由用户判断、修改或批准。
- Agent 可扩展用户的简短特殊要求，但必须告诉用户自己的理解并允许修改。
- Planning 只能在需求确认后生成；必须经用户批准才能进入 Composer。

## 不可违背的 PPT 原则

1. 禁止纯文字页；每页必须有论文来源明确的反应、机理、结构、谱图、表格或数据图。
2. 图多字少、页面较满；判断密度看真实有效图形面积，而不是图片容器尺寸。
3. 页数是柔性偏好，排版和科学内容完整性是硬要求。
4. 不机械按论文顺序。优先讲清科学问题、反应设计和完整机理，再进入优化、scope、证据和应用。
5. 纵向长图有可靠边界时安全裁分并横向重组；宽度不同则顶部对齐。不得切断结构、箭头、坐标、图例或面板标签。
6. A–D/A–E 多面板整图通常不配长文字，裁白边后放大到接近占满白色内容区。
7. 普通单图若显空，主图右移放大，左侧放置论文原文压缩出的短 callout。
8. Callout 圆圈必须内部透明，仅保留浅灰色 1.5 pt 细描边；内部文字使用黑色 Arial、26 pt、加粗、居中。圆圈不是灰色实心装饰。
9. 机理/表征与 scope/拓展应用语义不同时应拆页，不为页数强行拼接。
10. 首页包含论文标题、作者、期刊/年份/DOI 和 TOC Graphic；没有 TOC 时使用最能概括贡献的原论文视觉，不虚构。
11. 深蓝标题栏使用白色标题；可见表述尽量沿用论文术语，不能把 proposed/suggested/may 升级成确定结论。
12. Speaker notes 保留 `[Sources]`；需要讲稿时可加入中文讲稿。

## Composer/Validator 已实现

- 版式：`single_with_callout`、`multipanel_full`、`two_panels_fill`、`panel_triptych`、`weighted_two_images`、`stacked_mechanism_overview`、`image_full`。
- 支持安全裁白边、可靠面板裁分、派生图片溯源、自动拆页和页数上限诊断。
- 机理概要与完整催化循环可以前置组合。
- Validator 检查来源、规划顺序、页数范围、文件完整性、越界/重叠和真实视觉覆盖率；低于阈值返回 `insufficient_visual_coverage`。

## 已完成回归样本

- N-BPA 综述：用于首轮解析和单图/多面板/长图版式校准。
- Shintani Angew benzylsilanol：用于第二篇原始研究论文盲测和“机理前置”校准。
- Xue/Dong JACS C-demethylation：完成 10 页英文组会 PPT，验证 Scheme、优化、phenol/aniline scope、甲烷证据、Ru–H 循环和 DFT 的组合。

当前认可的最新 C-demethylation 成品：

`output/c-demethylation-fullflow-v1/6468e995-a330-cd54-1354-511f12235426/presentation.pptx`

该版本已经应用透明圆形 callout、黑色加粗大字，并通过 32 项测试和最终渲染检查。

## 下一阶段

- 提交前依赖审计已完成：`Pillow` 已加入核心依赖，新增 `competition` extra 安装 OpenAI SDK；Preflight 现在验证 `@oai/artifact-tool/package.json`，不会把空 Node modules 目录误判为就绪。
- API 工厂与 ASGI 入口已经分离，启动命令改为 `chemresearch_agent.api.asgi:app`，导入 `create_app` 不再创建运行数据目录。
- Composer 已删除 N-BPA 和特定反应类别的固定英文标题映射；无可靠 caption 时按通用 SlideType 生成标题，定量图布局由通用图表语义触发。
- 已新增公开依赖的 `PythonPptxPresentationRenderer`：Artifact Tool 可用时仍作为首选，不可用时自动降级；后备路径生成可编辑 PPTX、speaker notes、逐页 PNG、montage 和 layout JSON。清小搭服务器不再依赖 Codex 私有运行时。
- 后备 Renderer 已用 N-BPA 的 11 页真实 `SlideContent` 回归，视觉 montage 正常并通过 Validator（0 个问题）；同时增加无私有 Node 环境的 API 全链路测试。
- 中文 PNG 预览已加入平台相关 CJK 字体选择：Windows 优先微软雅黑/黑体，Linux 优先 Noto Sans CJK/WenQuanYi；缺失时写入 `cjk_preview_font_missing` 渲染诊断。真实中文预览已人工确认无方框。
- Validator 的标题换行门禁只匹配 `title-<数字>` 主标题，不再把作者和期刊行误判为标题；ASGI 回归现在真实加载 `api.asgi:app` 并请求 `/health`。
- 已新增论文发现与清小搭对话 Adapter：支持 `file.url`、DOI/doi.org、直接 PDF URL、自然语言 OpenAlex 检索、八步访谈、规划批准、后台生成、进度查询以及非流式/流式 `x_soda.attachments`。
- OpenAlex 真实联网回归已解析 DOI `10.1021/acs.chemrev.1c00383`，获得题录和 OSTI 开放全文地址；无开放 PDF 时明确要求用户上传，不绕过付费墙。

- 已完成第一版按钮式单页界面：上传、分析、逐题访谈、重点选择、特殊要求确认、规划修订/批准、生成、逐页预览和 PPTX 下载。
- 已增加 `GET /v1/artifacts/{artifact_id}/x-soda`，输出比赛要求的 URL-only `x_soda.attachments` PPT 描述。
- 已实现 `POST /v1/sessions/{id}/documents/url`：接收清小搭 `file.url`，只允许 HTTPS，并加入 50 MB 上限、超时、有限重定向、关闭环境代理以及私网/回环/链路本地/保留地址阻断。
- 已实现 `POST /v1/sessions/{id}/presentation/async` 与 `GET /v1/sessions/{id}/workflow-status`；前端生成按钮已改为异步提交并轮询 Composer、Renderer、Validator 进度，失败时显示结构化错误。
- 已实现 `POST /v1/sessions/{id}/presentation/retry`；可恢复失败会清除旧错误、回到 Composer 并重新执行，前端按钮自动变为“重试生成”。
- 已增加 `.env.example`、`chemresearch-preflight`、`GET /health/ready` 和 `docs/deployment.md`，可在比赛部署前检查 LLM、Node Renderer 与持久化目录。
- 当前异步任务使用 FastAPI `BackgroundTasks`，适合单进程 MVP；多进程/重启恢复需后续接持久化任务队列。
- 下一步根据比赛部署环境决定是否需要持久化任务队列，并接入正式 LLM 配置完成非 fixture 的在线全链路验收。

## Browser 诊断记录

- Browser 插件目录、`browser-client.mjs`、Windows 临时目录和 Codex 缓存目录均存在。
- `node_repl` 在执行任何 JavaScript 之前即返回 `failed to write kernel assets: 系统找不到指定的路径 (os error 3)`；重置内核后仍复现。
- 因此故障不在 FastAPI 页面、Browser 插件是否安装或 Chrome 扩展，而在 Codex 桌面端为当前任务初始化 JavaScript 内核资产目录的阶段。
- 建议恢复顺序：完全退出并重启 ChatGPT/Codex 桌面应用；确认 `Settings > Browser` 中内置 Browser 已启用；需要深入页面调试时再启用 Developer mode 的 full CDP access。Chrome 扩展不是本项目所必需。
- 2026-08-16 重启桌面应用后底层运行环境恢复，已成功连接 Codex 内置 Browser 并完成真实页面复核。
- 桌面端和 390 px 移动端均无 DOM 横向溢出；五步进度条在移动端正确切换为单列；上传按钮初始禁用；页面控制台无 error/warning。Browser 视觉复核门禁现已关闭。
- 用更多期刊、不同 Figure 结构和 Supporting Information 做盲测回归。
- 每次用户视觉反馈继续固化为通用 Composer/Renderer 规则与自动测试，避免写死单篇论文坐标。

## 真实浏览器全流程回归（2026-08-16）

- 已在 Codex 内置 Browser 中完成：上传 N-BPA PDF、13 页解析、逐步需求访谈、约 10 页规划、批准、Composer、Artifact Tool 渲染、Validator、逐页预览和下载入口。
- 本轮因未配置正式 LLM，仅 `Literature Analysis` 使用了明确标记的确定性测试 fixture；PDF 解析、访谈、Planning、Composer、Renderer、Validator 和 Web/API 均为正式实现。
- 首次生成暴露两项真实缺陷：验证失败退回 `COMPOSING` 后前端无限轮询；英文 Composer 直接使用过长结论句作为标题。
- 已修复：工作流现在用 `validation_failed` 阶段终止轮询、展示失败产物与诊断并允许重新生成；需求访谈完成后旧问题卡会替换成“汇报要求已确认”；英文标题优先使用简洁 caption/语义标题。
- 修复后浏览器回归成功：11 页、11 张预览、PPTX 4,239,578 bytes、自动验证通过且 0 个问题；下载地址正常生成。
- 回归产物：`tmp/browser-demo-data/artifacts/presentations/959a9c2b-d9ba-26bd-9058-eb373d33a136/presentation.pptx`（临时测试产物，不作为正式化学内容质量样本）。
- 当前代码检查：Ruff 通过，Pytest 42/42 通过。
