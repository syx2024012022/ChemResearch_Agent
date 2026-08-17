from __future__ import annotations

import re
import time
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from chemresearch_agent.domain.models import RequirementsQuestion, SlidePlan

SESSION_PATTERN = re.compile(r"<!--\s*chemresearch-session:([0-9a-f-]{36})\s*-->")

WELCOME_MESSAGE = """👋 你好，我是 ChemDeck——把有机化学论文变成组会 PPT 的智能体。

你可以上传论文 PDF，也可以提供 PDF 直链、DOI 或论文主题。我会解析全文、提炼关键反应与
机理，与你逐步确认汇报要求，并生成图多字少、带来源备注的可编辑 PPTX。

当前主要针对有机化学论文优化。DOI 和主题检索只能自动获取合法开放的 PDF；如果论文位于
付费墙后，仍需要你上传 PDF。

你可以这样开始：
1. 上传论文 PDF，生成组会 PPT
2. 发送 DOI 或 HTTPS PDF 直链
3. 描述论文题目或研究方向，让我查找开放论文
4. 回复“能力边界”，查看完整限制"""

CAPABILITY_MESSAGE = """【ChemDeck 目前能做什么】
✅ 解析有机化学论文 PDF，包括正文、页码、图注及 Figure/Scheme 等素材
✅ 接收 PDF 上传、HTTPS PDF 直链和清小搭 file.url
✅ 解析 DOI / doi.org 链接，并通过 OpenAlex 查找合法开放全文
✅ 根据题目或研究方向检索候选论文
✅ 分析背景、创新点、反应设计、关键结果、机理和局限
✅ 分步确认需求和规划，批准后输出可编辑 PPTX、预览、讲稿备注及来源

【暂未实现 / 已知限制】
⚠️ 主要针对有机化学论文优化，其他学科效果不保证
⚠️ 不绕过出版商付费墙；没有开放全文时需要用户上传 PDF
⚠️ 普通出版网页和任意 HTML 页面暂不能可靠转换为论文全文
⚠️ 清小搭 file_id 暂不支持，需要平台提供 file.url
⚠️ 纯扫描件缺少完整 OCR 支持，解析能力有限
⚠️ 文献分析需要配置模型 API Key；未配置时不会生成伪造内容
⚠️ 超过约 12 万字符的论文尚未自动分块分析
⚠️ 支持手动重试，但尚未实现诊断后自动修订并再次验证的自治循环
⚠️ PNG 预览不是 PowerPoint 原生截图，不同环境的最终显示可能略有差异
⚠️ 当前持久化和后台任务适合比赛演示及单实例部署，不适合高并发生产服务"""


def is_capability_question(text: str) -> bool:
    lowered = text.casefold().strip()
    return any(
        marker in lowered
        for marker in ("能力边界", "有哪些限制", "什么限制", "能做什么", "limitations")
    )


def is_greeting(text: str) -> bool:
    return text.casefold().strip(" !！。,.，") in {"你好", "您好", "hello", "hi", "开始"}


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: str | list[dict[str, Any]] | None = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    model: str | None = None
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    session_id: str | None = Field(default=None, alias="sessionId")


def last_user_input(request: ChatCompletionRequest) -> tuple[str, list[dict[str, str]]]:
    message = next((item for item in reversed(request.messages) if item.role == "user"), None)
    if message is None:
        raise ValueError("chat request requires a user message")
    if isinstance(message.content, str):
        return message.content.strip(), []
    texts: list[str] = []
    files: list[dict[str, str]] = []
    for part in message.content or []:
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            texts.append(part["text"])
        if part.get("type") == "file" and isinstance(part.get("file"), dict):
            file = part["file"]
            if file.get("url"):
                files.append(
                    {"url": str(file["url"]), "filename": str(file.get("filename") or "paper.pdf")}
                )
            elif file.get("file_id"):
                raise ValueError("file.file_id is not supported; ask 清小搭 to send file.url")
    return "\n".join(texts).strip(), files


def find_session_id(request: ChatCompletionRequest) -> UUID | None:
    for message in reversed(request.messages):
        values = [message.content] if isinstance(message.content, str) else []
        for part in message.content or [] if isinstance(message.content, list) else []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                values.append(part["text"])
        for value in values:
            match = SESSION_PATTERN.search(value or "")
            if match:
                return UUID(match.group(1))
    return None


def with_session(text: str, session_id: UUID | None) -> str:
    return f"{text}\n\n<!-- chemresearch-session:{session_id} -->" if session_id else text


def render_question(question: RequirementsQuestion) -> str:
    lines = [question.prompt]
    if question.recommendation:
        lines.append(f"\n建议：{question.recommendation}")
    if question.options:
        lines.append("")
        for index, option in enumerate(question.options, start=1):
            suffix = "（推荐）" if option.recommended else ""
            description = f" — {option.description}" if option.description else ""
            lines.append(f"{index}. {option.label}{suffix}{description}")
    return "\n".join(lines)


def parse_question_answer(question: RequirementsQuestion, text: str):
    value = text.strip()
    lowered = value.casefold()
    if question.input_kind == "text":
        return value
    if question.input_kind == "boolean":
        positive = ("是", "确认", "可以", "需要", "yes", "ok", "没问题")
        negative = ("否", "不", "no", "不需要", "修改")
        if any(item in lowered for item in negative):
            return False
        if any(item in lowered for item in positive):
            return True
        raise ValueError("请回答“是/否”或“确认/修改”")
    if question.input_kind == "multi_choice":
        if any(item in lowered for item in ("全部", "都要", "all")):
            return [option.value for option in question.options]
        matches = [
            option.value
            for index, option in enumerate(question.options, start=1)
            if option.label.casefold() in lowered
            or option.value.casefold() in lowered
            or str(index) in re.findall(r"\d+", value)
        ]
        return matches or [value]
    for index, option in enumerate(question.options, start=1):
        if (
            value == str(index)
            or option.label.casefold() in lowered
            or option.value.casefold() in lowered
        ):
            return option.value
    raise ValueError("请回复选项编号或选项文字")


def render_plan(plan: SlidePlan) -> str:
    lines = [f"已生成 {len(plan.slides)} 页规划："]
    lines.extend(f"{index}. {slide.key_message}" for index, slide in enumerate(plan.slides, 1))
    lines.append("\n请回复“批准”开始生成，或在网页端提交详细修改意见。")
    return "\n".join(lines)


def is_approval(text: str) -> bool:
    lowered = text.casefold()
    if any(item in lowered for item in ("不批准", "不同意", "先修改", "reject")):
        return False
    return any(item in lowered for item in ("批准", "确认", "可以", "没问题", "approve"))


def completion_payload(content: str, *, attachments: list[dict] | None = None) -> dict:
    payload = {
        "id": f"chatcmpl-{uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "chemresearch-agent",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    if attachments:
        payload["x_soda"] = {"attachments": attachments}
    return payload
