from __future__ import annotations

from collections.abc import Iterable

from pydantic import Field, model_validator

from chemresearch_agent.domain.enums import ClaimBasis
from chemresearch_agent.domain.errors import EvidenceGroundingError
from chemresearch_agent.domain.models import (
    DocumentParseResult,
    DomainModel,
    EvidenceRef,
    GroundedClaim,
    PaperAnalysis,
    PaperMetadata,
    ReactionAnalysis,
    SourceBlock,
)
from chemresearch_agent.tools.llm import StructuredLlmClient


class ClaimDraft(DomainModel):
    text: str
    basis: ClaimBasis
    source_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def explicit_claim_has_source(self) -> ClaimDraft:
        if self.basis == ClaimBasis.EXPLICIT and not self.source_ids:
            raise ValueError("explicit claims require at least one source_id")
        return self


class ReactionDraft(DomainModel):
    transformation: str
    catalyst: str | None = None
    reagents: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    mechanism: ClaimDraft | None = None
    key_intermediates: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class LiteratureAnalysisDraft(DomainModel):
    metadata: PaperMetadata
    research_context: list[ClaimDraft] = Field(default_factory=list)
    research_gap: list[ClaimDraft] = Field(default_factory=list)
    hypothesis: list[ClaimDraft] = Field(default_factory=list)
    innovations: list[ClaimDraft] = Field(default_factory=list)
    reactions: list[ReactionDraft] = Field(default_factory=list)
    key_results: list[ClaimDraft] = Field(default_factory=list)
    limitations: list[ClaimDraft] = Field(default_factory=list)
    important_source_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


SYSTEM_PROMPT = """你是一名严谨的有机化学文献分析员。输出必须符合给定结构。
只可引用输入目录中真实存在的 source_id，不得编造来源、实验数据或机理结论。
explicit 表示原文明确陈述；synthesized 表示由多个原文片段归纳；inferred 表示分析性推断。
explicit 必须有 source_ids；synthesized 应尽量提供多个来源。
inferred 可以无来源，但措辞必须表明是推断。
区分作者报告的事实、综述作者的归纳与未来展望。对综述论文，不要把综述写作本身误报为新反应发现。
化学式、催化剂、试剂、条件和数值必须忠实保留。分析文字使用简体中文，专有名词可保留英文。
"""


class LiteratureAnalysisSkill:
    name = "literature_analysis"
    version = "0.1.0"

    def __init__(self, llm: StructuredLlmClient, *, max_input_characters: int = 120_000) -> None:
        self._llm = llm
        self._max_input_characters = max_input_characters

    def analyze(self, document: DocumentParseResult) -> PaperAnalysis:
        prompt = self._build_prompt(document)
        result = self._llm.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
            response_model=LiteratureAnalysisDraft,
            operation="literature_analysis",
        )
        return self._ground(document, result.value)

    def _build_prompt(self, document: DocumentParseResult) -> str:
        header = (
            f"文件名: {document.file_name}\n页数: {document.page_count}\n"
            f"解析元数据: {document.metadata}\n\n来源目录:\n"
        )
        entries: list[str] = []
        for block in document.blocks:
            if not block.text:
                continue
            label = block.label or ""
            entries.append(
                f"[{block.source_id} | page {block.page_number} | {block.kind.value} | {label}]\n"
                f"{block.text.strip()}\n"
            )
        for figure in document.figures:
            entries.append(
                f"[FIGURE {figure.figure_id} | page {figure.page_number} | "
                f"caption_source_id {figure.caption_source_id}]\n{figure.caption}\n"
            )
        instruction = (
            "\n任务：提取元数据、研究背景/空白/假设、创新、关键反应、结果和局限。"
            "每个结论绑定上述 source_id；important_source_ids 仅列最适合后续做组会幻灯片的来源。"
        )
        budget = self._max_input_characters - len(header) - len(instruction)
        body = "\n".join(entries)
        if len(body) > budget:
            raise ValueError(
                "document exceeds the single-pass literature analysis limit; chunking is required"
            )
        return header + body + instruction

    @staticmethod
    def _ground(document: DocumentParseResult, draft: LiteratureAnalysisDraft) -> PaperAnalysis:
        sources = {block.source_id: block for block in document.blocks}

        def evidence(source_ids: Iterable[str]) -> list[EvidenceRef]:
            refs: list[EvidenceRef] = []
            for source_id in dict.fromkeys(source_ids):
                block = sources.get(source_id)
                if block is None:
                    raise EvidenceGroundingError(
                        f"unknown source_id returned by model: {source_id}"
                    )
                refs.append(_to_evidence(document, block))
            return refs

        def claim(value: ClaimDraft) -> GroundedClaim:
            return GroundedClaim(
                text=value.text,
                basis=value.basis,
                evidence=evidence(value.source_ids),
            )

        unknown_important = set(draft.important_source_ids) - sources.keys()
        if unknown_important:
            invalid = ", ".join(sorted(unknown_important))
            raise EvidenceGroundingError(
                f"unknown important source_ids returned by model: {invalid}"
            )

        reactions = [
            ReactionAnalysis(
                transformation=item.transformation,
                catalyst=item.catalyst,
                reagents=item.reagents,
                conditions=item.conditions,
                mechanism=claim(item.mechanism) if item.mechanism else None,
                key_intermediates=item.key_intermediates,
                evidence=evidence(item.source_ids),
            )
            for item in draft.reactions
        ]
        return PaperAnalysis(
            document_id=document.document_id,
            metadata=draft.metadata,
            research_context=[claim(item) for item in draft.research_context],
            research_gap=[claim(item) for item in draft.research_gap],
            hypothesis=[claim(item) for item in draft.hypothesis],
            innovations=[claim(item) for item in draft.innovations],
            reactions=reactions,
            key_results=[claim(item) for item in draft.key_results],
            limitations=[claim(item) for item in draft.limitations],
            important_source_ids=list(dict.fromkeys(draft.important_source_ids)),
            warnings=document.warnings + draft.warnings,
        )


def _to_evidence(document: DocumentParseResult, block: SourceBlock) -> EvidenceRef:
    excerpt = block.text.strip()[:500] if block.text else None
    return EvidenceRef(
        source_id=block.source_id,
        document_id=document.document_id,
        page_number=block.page_number,
        kind=block.kind,
        excerpt=excerpt,
        label=block.label,
    )
