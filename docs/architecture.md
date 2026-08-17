# 架构基线

## 目标

系统必须先形成带原文证据的论文理解，再收集汇报需求、规划叙事并等待用户确认，最后才允许生成 PPT。首版采用单 Orchestrator 调用多个 Skill，不采用多 Agent。

## 分层及依赖方向

```text
API → Application → Domain
         ↓            ↑
      Skill ports  Skill implementations
         ↓
 Tools / Infrastructure adapters
```

- `domain`：稳定业务模型和规则，不依赖 Web、模型 SDK、PDF 或 PPT 库。
- `application`：状态推进、用例编排及确认门禁，不承载专业推理。
- `skills`：专业规则、Prompt、工具组合和结构化输出验证。
- `tools`：PDF、LLM、化学计算和 PPT 渲染等能力。
- `infrastructure`：持久化、队列、对象存储和观测性适配。
- `api`：输入输出适配，不直接调用模型或渲染库。

## 状态机

```text
CREATED
  → DOCUMENT_UPLOADED
  → PARSING
  → ANALYZING
  → NEEDS_REQUIREMENTS
  → PLANNING
  → AWAITING_PLAN_APPROVAL
  → COMPOSING
  → RENDERING
  → VALIDATING
  → COMPLETED
```

`FAILED_RETRYABLE` 允许回到发生故障的处理阶段；`FAILED_FINAL` 和 `CANCELLED` 是终态。非法跳转由领域错误拒绝。

## 质量门禁

1. 明确声称来自论文的结论必须包含至少一个 `EvidenceRef`。
2. 只有完成论文分析后才能提交汇报需求。
3. 只有生成 `SlidePlan` 并获得用户批准后才能进入内容编排。
4. 只有渲染产物通过验证后才能进入 `COMPLETED`。

## 持久化策略

MVP 使用 JSON 文件保存会话，以原子替换避免半写文件，并以 `version` 做乐观并发控制。该实现遵循 `SessionRepository` 端口，后续可替换为 SQLite/PostgreSQL 而不修改领域模型和 Orchestrator。

## 当前实现状态

端到端 MVP 已贯通 PDF 上传、PyMuPDF 解析、Figure 裁切、Literature Analysis、
用户需求门禁、Presentation Planning、规划审批、Composer、Artifact Tool PPTX
渲染和确定性验证。Planning、Composer、Renderer 与 Validator 均位于端口之后，
后续可替换为模型驱动 Skill、课题组模板或其他渲染后端，而不改变状态机。
