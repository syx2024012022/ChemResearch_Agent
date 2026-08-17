from __future__ import annotations

from typing import Any
from uuid import UUID

from chemresearch_agent.application.orchestrator import AgentOrchestrator
from chemresearch_agent.domain.enums import AudienceLevel, PresentationPurpose, SessionStatus
from chemresearch_agent.domain.errors import InvalidTransitionError
from chemresearch_agent.domain.models import (
    AgentSession,
    PaperAnalysis,
    PresentationRequirements,
    RequirementOption,
    RequirementsInterview,
    RequirementsQuestion,
)

STEPS = (
    "purpose",
    "occasion",
    "language",
    "focus_topics",
    "include_speaker_notes",
    "special_instructions",
    "special_confirmation",
    "slide_count_range",
)

SLIDE_RANGES = {
    "about_8": (7, 9),
    "about_10": (9, 11),
    "about_12": (11, 13),
    "about_15": (14, 18),
}


class GuidedRequirementsService:
    """Runs an Agent-led, resumable requirements interview."""

    def __init__(self, orchestrator: AgentOrchestrator) -> None:
        self._orchestrator = orchestrator

    def start(self, session_id: UUID) -> tuple[AgentSession, RequirementsQuestion]:
        session = self._orchestrator.get_session(session_id)
        if session.status != SessionStatus.NEEDS_REQUIREMENTS or session.paper_analysis is None:
            raise InvalidTransitionError("requirements interview starts only after paper analysis")
        if session.requirements_interview is None:
            interview = RequirementsInterview(
                focus_suggestions=_suggest_focus(session.paper_analysis)
            )
            session = self._orchestrator.record_requirements_interview(session_id, interview)
        return session, self.question(session)

    def answer(
        self, session_id: UUID, step: str, value: Any
    ) -> tuple[AgentSession, RequirementsQuestion | None]:
        session = self._orchestrator.get_session(session_id)
        interview = session.requirements_interview
        if session.status != SessionStatus.NEEDS_REQUIREMENTS or interview is None:
            raise InvalidTransitionError("no active requirements interview")
        if step != interview.current_step:
            raise ValueError(f"expected answer for {interview.current_step}, received {step}")

        value = _validate_answer(step, value, interview)
        if step == "special_instructions":
            interview.user_special_request = value
            interview.expanded_special_instructions = _expand_special_request(value)
        elif step == "special_confirmation" and value is False:
            interview.current_step = "special_instructions"
            session = self._orchestrator.record_requirements_interview(session_id, interview)
            return session, self.question(session)
        else:
            interview.answers[step] = value

        next_index = STEPS.index(step) + 1
        if next_index < len(STEPS):
            interview.current_step = STEPS[next_index]
            session = self._orchestrator.record_requirements_interview(session_id, interview)
            return session, self.question(session)

        interview.completed = True
        session = self._orchestrator.record_requirements_interview(session_id, interview)
        requirements = PresentationRequirements(
            purpose=PresentationPurpose(interview.answers["purpose"]),
            audience_level=AudienceLevel.CHEMISTRY,
            occasion=interview.answers["occasion"],
            language=interview.answers["language"],
            focus_topics=interview.answers["focus_topics"],
            min_slide_count=SLIDE_RANGES[interview.answers["slide_count_range"]][0],
            max_slide_count=SLIDE_RANGES[interview.answers["slide_count_range"]][1],
            include_speaker_notes=interview.answers["include_speaker_notes"],
            special_instructions=interview.expanded_special_instructions,
        )
        return self._orchestrator.submit_requirements(session_id, requirements), None

    def question(self, session: AgentSession) -> RequirementsQuestion:
        interview = session.requirements_interview
        if interview is None:
            raise InvalidTransitionError("requirements interview has not started")
        step = interview.current_step
        if step == "purpose":
            return RequirementsQuestion(
                step=step,
                prompt="这次汇报的主要用途是什么？",
                input_kind="single_choice",
                options=[
                    RequirementOption(value="group_meeting", label="课题组组会", recommended=True),
                    RequirementOption(value="journal_club", label="文献分享"),
                    RequirementOption(value="conference", label="会议报告"),
                    RequirementOption(value="teaching", label="课程讲解"),
                ],
            )
        if step == "occasion":
            return RequirementsQuestion(
                step=step,
                prompt="汇报场合和主要听众是什么？",
                input_kind="text",
                recommendation="例如：课题组内部，听众为有机化学方向研究生和老师。",
            )
        if step == "language":
            return RequirementsQuestion(
                step=step,
                prompt="幻灯片使用什么语言？",
                input_kind="single_choice",
                options=[
                    RequirementOption(value="en", label="英文", recommended=True),
                    RequirementOption(value="zh-CN", label="中文"),
                    RequirementOption(value="bilingual", label="中英结合"),
                ],
                recommendation="专业组会默认使用英文；如有中文或双语要求可在此选择，也可写入特殊要求。",
            )
        if step == "focus_topics":
            options = [
                RequirementOption(value=item, label=item, recommended=True)
                for item in interview.focus_suggestions
            ]
            return RequirementsQuestion(
                step=step,
                prompt="根据论文内容，我建议重点讲下面几条。哪些贴合你的汇报意图？可以增删或改写。",
                input_kind="multi_choice",
                options=options,
                recommendation="默认全部保留，再由规划阶段分配篇幅。",
            )
        if step == "include_speaker_notes":
            return RequirementsQuestion(
                step=step,
                prompt="需要为每页生成讲稿备注吗？",
                input_kind="boolean",
                recommendation="建议保留，正文可少字，解释和来源放入备注。",
            )
        if step == "special_instructions":
            return RequirementsQuestion(
                step=step,
                prompt="还有什么版式、内容或风格要求？一句话描述即可，我会先扩展理解再请你确认。",
                input_kind="text",
            )
        if step == "special_confirmation":
            return RequirementsQuestion(
                step=step,
                prompt="我将你的简短要求扩展为下面的执行约束，是否准确？不准确可退回修改。",
                input_kind="boolean",
                recommendation=interview.expanded_special_instructions,
            )
        return RequirementsQuestion(
            step=step,
            prompt="你希望整套幻灯片大约多少页？最终页数会根据文章内容在区间内调整。",
            input_kind="single_choice",
            options=[
                RequirementOption(value="about_8", label="约 8 页", description="7–9 页"),
                RequirementOption(
                    value="about_10", label="约 10 页", description="9–11 页", recommended=True
                ),
                RequirementOption(value="about_12", label="约 12 页", description="11–13 页"),
                RequirementOption(value="about_15", label="约 15 页", description="14–18 页"),
            ],
            recommendation="这篇综述先按约 10 页规划，再由内容密度决定实际页数。",
        )


def _suggest_focus(analysis: PaperAnalysis) -> list[str]:
    suggestions: list[str] = []
    for claim in analysis.innovations[:2] + analysis.key_results[:2]:
        if claim.text not in suggestions:
            suggestions.append(claim.text)
    for reaction in analysis.reactions[:2]:
        if reaction.transformation not in suggestions:
            suggestions.append(reaction.transformation)
    if not suggestions:
        suggestions = ["研究背景与核心问题", "关键发现及其证据", "局限与未来方向"]
    return suggestions[:5]


def _expand_special_request(value: str) -> str:
    request = value.strip()
    if not request:
        return "采用清晰、证据可追溯的有机化学组会版式。"
    additions = []
    if "图多" in request or "字少" in request:
        additions.append("以论文反应图和机理图为主要视觉，每页只保留一句关键结论与必要标签")
    if "满" in request or "紧凑" in request:
        additions.append("提高有效信息占比但保持页边距、字号和图注可读，不通过缩小字号硬塞")
    if "格式" in request or "统一" in request:
        additions.append("统一标题、页码、Figure 来源和配色层级")
    if not additions:
        additions.append("将该要求应用到模板选择、内容密度和视觉检查中")
    return f"用户原始要求：{request}。Agent 执行理解：" + "；".join(additions) + "。"


def _validate_answer(step: str, value: Any, interview: RequirementsInterview) -> Any:
    if step == "slide_count_range":
        if value not in SLIDE_RANGES:
            raise ValueError("unknown slide_count_range")
    elif step in {"include_speaker_notes", "special_confirmation"}:
        if not isinstance(value, bool):
            raise ValueError(f"{step} must be boolean")
    elif step == "focus_topics":
        if not isinstance(value, list) or not value or not all(isinstance(x, str) for x in value):
            raise ValueError("focus_topics must be a non-empty string list")
    elif not isinstance(value, str):
        raise ValueError(f"{step} must be text")
    return value
