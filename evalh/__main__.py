"""評価ハーネスを動かす。

    .venv/bin/python -m evalh                       # dev を偽物の流れ2つで測る
    .venv/bin/python -m evalh --split heldout       # 最終確認用（自動改善には使わない）
    .venv/bin/python -m evalh --pipeline mypkg.mod:factory --out report.json --md report.md

--pipeline には、Pipeline を返す引数なしの関数を「モジュール:関数名」で指定する。何度でも書ける。
"""
import argparse
import importlib
import json
import sys
from pathlib import Path

from .cases import DEFAULT_DIR, SPLITS, STUDENTS, load_cases
from .report import to_markdown
from .runner import EvalConfig, evaluate

DEFAULT_PIPELINES = ["evalh.fakes:lexicon_pipeline", "evalh.fakes:flat_pipeline"]


def load_pipeline(spec: str):
    module_name, _, attr = spec.partition(":")
    if not attr:
        raise SystemExit(f"--pipeline は「モジュール:関数名」で書いてください: {spec}")
    return getattr(importlib.import_module(module_name), attr)()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evalh", description="模擬提出物で確認事項の流れを測る")
    parser.add_argument("--cases", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--split", choices=SPLITS, default="dev")
    parser.add_argument("--student", choices=STUDENTS, default="standard", help="生徒役の水準。weak は説明が苦手な生徒")
    parser.add_argument("--pipeline", action="append", dest="pipelines")
    parser.add_argument("--budget", type=float, action="append", dest="budgets", help="持ち時間（秒）。何度でも書ける")
    parser.add_argument("--out", type=Path, help="結果の JSON を書き出す先")
    parser.add_argument("--md", type=Path, help="結果の表（Markdown）を書き出す先。なければ標準出力")
    args = parser.parse_args(argv)

    cases = load_cases(args.cases, args.split, args.student)
    if not cases:
        raise SystemExit(f"{args.cases} に {args.split} の提出物がありません")
    config = EvalConfig(budgets=tuple(args.budgets)) if args.budgets else EvalConfig()
    reports = [evaluate(load_pipeline(spec), cases, config) for spec in args.pipelines or DEFAULT_PIPELINES]

    if args.out:
        args.out.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown = to_markdown(reports)
    if args.md:
        args.md.write_text(markdown, encoding="utf-8")
    else:
        sys.stdout.write(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
