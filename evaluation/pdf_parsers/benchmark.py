from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from uuid import uuid4

from .base import PdfParserAdapter, normalize_text
from .models import ParserRunResult, ParserRunStatus, ParserScore, ScoreComponent


class ParserBenchmark:
    def __init__(self, gold_path: Path) -> None:
        self.gold_path = gold_path
        self.gold: dict[str, Any] = json.loads(gold_path.read_text(encoding="utf-8"))

    def run(
        self,
        pdf_path: Path,
        output_root: Path,
        adapters: Iterable[PdfParserAdapter],
    ) -> tuple[list[ParserRunResult], list[ParserScore]]:
        document_id = uuid4()
        runs = [adapter.run(document_id, pdf_path, output_root) for adapter in adapters]
        scores = [self.score(run) for run in runs]
        self.write_report(pdf_path, output_root, runs, scores)
        return runs, scores

    def score(self, run: ParserRunResult) -> ParserScore:
        if run.document is None or run.status in {ParserRunStatus.SKIPPED, ParserRunStatus.FAILED}:
            return ParserScore(
                parser_name=run.parser_name,
                status=run.status,
                score=0,
                components=[],
                gates={"completed": False},
                passes_required_gates=False,
                recommendation="未运行" if run.status == ParserRunStatus.SKIPPED else "淘汰",
            )

        document = run.document
        full_text = normalize_text(
            "\n".join(block.text or "" for block in document.blocks) + "\n" + (run.markdown or "")
        )
        folded = full_text.casefold()
        anchors = self.gold["text_anchors"]
        anchor_hits = sum(normalize_text(anchor).casefold() in folded for anchor in anchors)
        text_points = 20 * anchor_hits / len(anchors)

        headings = self.gold["sections"]
        heading_positions = [folded.find(normalize_text(value).casefold()) for value in headings]
        found_headings = sum(position >= 0 for position in heading_positions)
        order_ok = all(
            left < right
            for left, right in zip(heading_positions, heading_positions[1:], strict=False)
            if left >= 0 and right >= 0
        )
        structure_points = 15 * found_headings / len(headings) + (5 if order_ok else 0)

        caption_blocks = {
            block.label.casefold(): block
            for block in document.blocks
            if block.label and re.fullmatch(r"Figure\s+\d+", block.label, re.IGNORECASE)
        }
        expected_figures = self.gold["figures"]
        found_figures = 0
        correct_pages = 0
        coordinate_count = 0
        for label, expected_page in expected_figures.items():
            block = caption_blocks.get(label.casefold())
            if block:
                found_figures += 1
                correct_pages += block.page_number == expected_page
                coordinate_count += block.bounding_box is not None
            elif re.search(rf"{re.escape(label)}\s*\.", full_text, re.IGNORECASE):
                found_figures += 1
        figure_points = (
            10 * found_figures / len(expected_figures)
            + 10 * correct_pages / len(expected_figures)
            + 10 * coordinate_count / len(expected_figures)
        )

        metadata_text = " ".join(document.metadata.values()).casefold()
        metadata_checks = {
            "pages": document.page_count == self.gold["page_count"],
            "title": normalize_text(self.gold["title"]).casefold() in metadata_text
            or normalize_text(self.gold["title"]).casefold() in folded,
            "doi": self.gold["doi"].casefold() in metadata_text
            or self.gold["doi"].casefold() in folded,
            "authors": all(
                author.casefold() in (metadata_text + " " + folded)
                for author in self.gold["authors"]
            ),
            "references": f"({self.gold['reference_count']})" in full_text,
        }
        metadata_points = 2 * sum(metadata_checks.values())
        robustness_points = 5 if run.status == ParserRunStatus.SUCCESS else 3
        components = [
            ScoreComponent(
                name="正文完整性",
                earned=text_points,
                possible=20,
                details=f"命中 {anchor_hits}/{len(anchors)} 个文字锚点",
            ),
            ScoreComponent(
                name="阅读顺序与章节",
                earned=structure_points,
                possible=20,
                details=(
                    f"识别 {found_headings}/{len(headings)} 个主体章节；"
                    f"顺序={'正确' if order_ok else '错误'}"
                ),
            ),
            ScoreComponent(
                name="Figure 与坐标",
                earned=figure_points,
                possible=30,
                details=(
                    f"识别 {found_figures}/11，页码正确 {correct_pages}/11，"
                    f"坐标 {coordinate_count}/11"
                ),
            ),
            ScoreComponent(
                name="元数据与参考文献",
                earned=metadata_points,
                possible=10,
                details=", ".join(
                    f"{key}={'是' if value else '否'}" for key, value in metadata_checks.items()
                ),
            ),
            ScoreComponent(
                name="部署复杂度",
                earned=run.deployment_points,
                possible=15,
                details=f"耗时 {run.elapsed_seconds:.2f}s；部署基准分 {run.deployment_points}/15",
            ),
            ScoreComponent(
                name="错误处理",
                earned=robustness_points,
                possible=5,
                details=f"状态 {run.status}；警告 {len(run.warnings)} 条",
            ),
        ]
        score = round(sum(component.earned for component in components), 2)
        gates = {
            "all_pages": document.page_count == self.gold["page_count"],
            "title_authors_doi": metadata_checks["title"]
            and metadata_checks["authors"]
            and metadata_checks["doi"],
            "five_sections": found_headings == len(headings) and order_ok,
            "ten_of_eleven_figures": found_figures >= 10 and correct_pages >= 10,
            "evidence_coordinates": coordinate_count >= 10,
            "visual_review": run.parser_name in self.gold.get("visual_review_passed", []),
        }
        passes = all(gates.values())
        recommendation = "采用" if passes else ("备用" if score >= 65 else "淘汰")
        return ParserScore(
            parser_name=run.parser_name,
            status=run.status,
            score=score,
            components=components,
            gates=gates,
            passes_required_gates=passes,
            recommendation=recommendation,
        )

    def write_report(
        self,
        pdf_path: Path,
        output_root: Path,
        runs: list[ParserRunResult],
        scores: list[ParserScore],
    ) -> Path:
        output_root.mkdir(parents=True, exist_ok=True)
        run_path = output_root / "runs.json"
        score_path = output_root / "scores.json"
        report_path = output_root / "report.md"
        run_path.write_text(
            json.dumps([run.model_dump(mode="json") for run in runs], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        score_path.write_text(
            json.dumps(
                [score.model_dump(mode="json") for score in scores],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        lines = [
            "# PDF 解析器基准报告",
            "",
            f"- 样本：`{pdf_path.name}`",
            f"- 黄金清单：`{self.gold_path}`",
            "",
            "| 解析器 | 状态 | 得分 | 必选门禁 | 建议 | 耗时 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        by_name = {run.parser_name: run for run in runs}
        for score in sorted(scores, key=lambda value: value.score, reverse=True):
            run = by_name[score.parser_name]
            lines.append(
                f"| {score.parser_name} | {score.status} | {score.score:.2f} | "
                f"{'通过' if score.passes_required_gates else '未通过'} | {score.recommendation} | "
                f"{run.elapsed_seconds:.2f}s |"
            )
        for score in scores:
            lines.extend(["", f"## {score.parser_name}", ""])
            if not score.components:
                run = by_name[score.parser_name]
                lines.append("；".join(run.warnings + run.errors) or "未产生结果。")
                continue
            for component in score.components:
                lines.append(
                    f"- {component.name}: {component.earned:.2f}/"
                    f"{component.possible:.0f} — {component.details}"
                )
            gate_text = "，".join(
                f"{key}={'通过' if value else '失败'}" for key, value in score.gates.items()
            )
            lines.append("- 门禁：" + gate_text)
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report_path
