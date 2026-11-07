"""指示文の自動改善を動かす。

    # 改善のループ（Gemini と合成コードの実行を使う）
    APP_ENV=local ALLOW_LOCAL_SANDBOX=1 GOOGLE_CLOUD_PROJECT=... .venv/bin/python -m rsi run --iterations 5

    # 結果（rsi_runs/ の summary.md）を読んで、よければ人が昇格する
    .venv/bin/python -m rsi promote rsi_runs/20261106-120000-probe_planner

    # 確認枠の結果から、見直しが要るかを調べる（企画案 p.20）
    .venv/bin/python -m rsi trigger --found 3 --sampled 12
"""
import argparse
import os
import sys
from pathlib import Path

from .trigger import needs_review, wilson_lower


def _cases(folders: list[Path], split: str, student: str) -> list:
    """いくつかのフォルダの模擬提出物をまとめる。1つの組だけに合わせた指示文にならないようにする。"""
    from evalh.cases import load_cases

    cases = [case for folder in folders for case in load_cases(folder, split=split, student=student)]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise SystemExit("フォルダをまたいで同じ名前の提出物があります")
    return cases


def _run(args) -> int:
    from google import genai

    from evalh.cases import DEFAULT_DIR, load_cases
    from qgen.sandbox import LocalDevSandbox

    from . import record, targets
    from .loop import MeasurementError, optimize
    from .proposer import GeminiProposer

    client = genai.Client(enterprise=True, project=os.environ["GOOGLE_CLOUD_PROJECT"], location=args.location)
    target = targets.probe_planner(client, args.model, LocalDevSandbox())
    if args.start:  # 前の実行の候補から続けて探す。ACTIVE（本番の版）は変えない
        from dataclasses import replace

        target = replace(target, initial=args.start.read_text(encoding="utf-8"))
    try:
        result = optimize(
            target,
            _cases(args.cases or [DEFAULT_DIR], "dev", args.student),
            _cases(args.cases or [DEFAULT_DIR], "heldout", args.student),
            GeminiProposer(client, args.proposer_model),
            iterations=args.iterations,
            repeats=args.repeats,
            workers=args.workers,
            log=lambda message: print(message, file=sys.stderr),
        )
    except MeasurementError as error:
        print(f"今の版を測れませんでした：{error}。Gemini の上限や接続を確かめてください", file=sys.stderr)
        return 1
    folder = record.write_run(result, meta={"cases": [str(folder) for folder in args.cases] if args.cases else ["evals/cases"], "student": args.student, "model": args.model, "proposer_model": args.proposer_model, "repeats": args.repeats, "start": str(args.start or "ACTIVE")})
    print(f"{record.DECISIONS[result.decision]}\n記録: {folder / 'summary.md'}")
    return 0


def _promote(args) -> int:
    from .record import promote

    name = promote(args.run, args.candidate, args.force)
    print(f"qgen/prompts の新しい版 {name} を ACTIVE にしました。差分をレビューしてからコミットしてください")
    return 0


def _trigger(args) -> int:
    lower = wilson_lower(args.found, args.sampled)
    verdict = "見直しが要ります（抽出率を2倍にして、指示文の改善を回す）" if needs_review(args.found, args.sampled) else "見直しは要りません"
    print(f"見逃し率 {args.found}/{args.sampled}、95%下限 {lower:.3f}：{verdict}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rsi", description="指示文の自動改善")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="改善のループを回す")
    run.add_argument("--target", choices=["probe_planner"], default="probe_planner")
    run.add_argument("--iterations", type=int, default=5)
    run.add_argument("--cases", type=Path, nargs="+", default=None, help="模擬提出物のフォルダ。いくつも渡すとまとめて測る（既定は evals/cases）")
    run.add_argument("--student", choices=["standard", "weak"], default="standard", help="生徒役の水準。weak は説明が苦手な生徒")
    run.add_argument("--workers", type=int, default=8, help="提出物を並行に測る数（Gemini の待ち時間を重ねる）")
    run.add_argument("--repeats", type=int, default=3, help="同じ指示文を測る回数。平均で比べ、ぶれより小さい差は改善とみなさない")
    run.add_argument("--model", default=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"))
    run.add_argument("--proposer-model", default=os.environ.get("RSI_PROPOSER_MODEL", "gemini-3.1-pro-preview"))
    run.add_argument("--location", default="global")
    run.add_argument("--start", type=Path, default=None, help="この指示文のファイルから探し始める（既定は ACTIVE の版）。例: rsi_runs/<日時>-probe_planner/candidates/c006.md")
    run.set_defaults(handler=_run)
    promote = commands.add_parser("promote", help="推薦された候補を本番の版にする（人が実行する）")
    promote.add_argument("run", type=Path)
    promote.add_argument("--candidate")
    promote.add_argument("--force", action="store_true")
    promote.set_defaults(handler=_promote)
    trigger = commands.add_parser("trigger", help="確認枠の結果から見直しが要るかを調べる")
    trigger.add_argument("--found", type=int, required=True)
    trigger.add_argument("--sampled", type=int, required=True)
    trigger.set_defaults(handler=_trigger)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
