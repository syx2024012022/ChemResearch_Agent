# 数据契约原则

## 严格输入

所有领域模型默认拒绝未知字段，防止 Prompt、API 和持久化层在版本演进时静默丢失数据。

## 证据模型

`EvidenceRef` 使用 `document_id + source_id + page_number` 定位论文证据，可附带摘录、图表标签和置信度。

`FigureRecord` 保存 Figure 编号、完整图注、所在页、图注文本块、裁切坐标、
裁切图片路径，以及正文中引用该 Figure 的 `source_id`。Composer 应优先消费
`FigureRecord`，不得重新从整页截图中猜测图片区域。

`GroundedClaim.basis` 区分：

- `explicit`：论文明确陈述，必须附证据。
- `synthesized`：根据多个来源归纳。
- `inferred`：模型推断，界面和 PPT 中必须显式标注。

## 规划与页面内容分离

`SlidePlan` 只描述页面目的、核心信息、证据和时间预算，不包含坐标及渲染细节。`SlideContent` 负责文案和视觉素材，`TemplateSpec` 负责槽位与容量，Renderer 只做确定性排版。模板槽位名称必须唯一，每个内容块也只能携带文字、来源素材或文件素材中的一种。

## 版本与可恢复性

每次合法状态转换都会：

- 增加会话 `version`
- 更新 `updated_at`
- 追加 `SessionEvent`

外部任务和 Skill 以后应使用 `session_id + operation + input_hash` 作为幂等依据。
