from __future__ import annotations

import argparse
from pathlib import Path

from .benchmark import ParserBenchmark
from .docling_adapter import DoclingAdapter
from .grobid_adapter import GrobidAdapter
from .mineru_adapter import MinerUAdapter
from .pdfplumber_adapter import PdfPlumberAdapter
from .pymupdf_adapter import PyMuPdfAdapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark PDF parser adapters")
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "--gold",
        type=Path,
        default=Path("benchmarks/pdf_parsers/n_boryl_pyridyl_anion.gold.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/parser_benchmarks/n_boryl_pyridyl_anion"),
    )
    parser.add_argument(
        "--parsers",
        nargs="+",
        choices=["pymupdf", "pdfplumber", "docling", "grobid", "mineru_cloud"],
        default=["pymupdf", "pdfplumber"],
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.pdf.is_file():
        raise SystemExit(f"PDF does not exist: {args.pdf}")
    adapters = {
        "pymupdf": PyMuPdfAdapter,
        "pdfplumber": PdfPlumberAdapter,
        "docling": DoclingAdapter,
        "grobid": GrobidAdapter,
        "mineru_cloud": MinerUAdapter,
    }
    benchmark = ParserBenchmark(args.gold)
    _, scores = benchmark.run(
        args.pdf,
        args.output,
        [adapters[name]() for name in args.parsers],
    )
    for score in sorted(scores, key=lambda value: value.score, reverse=True):
        print(
            f"{score.parser_name}: {score.status}, {score.score:.2f}/100, "
            f"gates={'PASS' if score.passes_required_gates else 'FAIL'}, "
            f"recommendation={score.recommendation}"
        )
    print(f"Report: {args.output / 'report.md'}")


if __name__ == "__main__":
    main()
