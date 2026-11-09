"""改善の記録と、人による昇格。

rsi_runs/<日時>-<対象>/ に、全候補の指示文・点数・却下の理由・親子関係と、今の版との差分を残す。
昇格（promote）は推薦された候補だけを qgen/prompts/ の新しい版にして ACTIVE を切り替える。
"""
import difflib
import json
from datetime import datetime
from pathlib import Path

from qgen import prompt_store

from .loop import NO_IMPROVEMENT, NOT_MEASURED, RECOMMENDED, REJECTED_BY_HELDOUT, RunResult

RUNS_DIR = Path(__file__).resolve().parent.parent / "rsi_runs"
DECISIONS = {
    RECOMMENDED: "推薦：heldout でも今の版より下がらなかった。差分を読んで、よければ promote する",
    NO_IMPROVEMENT: "改善なし：今の版より良い候補が見つからなかった",
    REJECTED_BY_HELDOUT: "見送り：dev では良かったが heldout で下がった（dev に合わせすぎた可能性）",
    NOT_MEASURED: "見送り：heldout を測る途中で AI の呼び出しが失敗した。上限や接続を確かめて、もう一度回す",
}


def _summary(result: RunResult) -> dict:
    return {
        "target": result.target,
        "best": result.best,
        "decision": result.decision,
        "heldout": result.heldout,
        "noise": result.noise,
        "candidates": [
            {
                "id": c.id,
                "parent": c.parent,
                "status": c.status,
                "score": c.score,
                "repeats": c.report.get("repeats") if c.report else None,
                "per_case": c.report["per_case"] if c.report else None,
                "reasons": c.reasons,
                "rationale": c.rationale,
            }
            for c in result.candidates
        ],
    }


def diff(old: str, new: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "今の版", "候補"))


def write_run(result: RunResult, root: Path = RUNS_DIR, now: datetime | None = None, meta: dict | None = None) -> Path:
    """meta には、どの条件で回したか（生徒役の水準、モデルなど）を入れる。"""
    folder = root / f"{(now or datetime.now()).strftime('%Y%m%d-%H%M%S')}-{result.target}"
    (folder / "candidates").mkdir(parents=True)
    for candidate in result.candidates:
        (folder / "candidates" / f"{candidate.id}.md").write_text(candidate.prompt, encoding="utf-8")
        if candidate.report:
            (folder / "candidates" / f"{candidate.id}.report.json").write_text(
                json.dumps({"report": candidate.report, "notes": candidate.notes}, ensure_ascii=False, indent=1), encoding="utf-8"
            )
    (folder / "run.json").write_text(json.dumps({"meta": meta or {}} | _summary(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (folder / "summary.md").write_text(summary_markdown(result, meta), encoding="utf-8")
    return folder


def summary_markdown(result: RunResult, meta: dict | None = None) -> str:
    base, best = result.candidates[0], result.candidate(result.best)
    lines = [
        f"# 指示文の自動改善：{result.target}",
        "",
        f"**判定**：{DECISIONS[result.decision]}",
        "",
        *([("条件：" + "、".join(f"{key} = {value}" for key, value in meta.items())), ""] if meta else []),
        f"今の版を何回か測ったときの点数の幅（ぶれ）：{result.noise:.3f}。これより小さい差は改善とみなしていない。",
        "",
        "| 候補 | 親 | 状態 | dev の点数 | 理由・改善役の説明 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in result.candidates:
        note = "；".join(c.reasons) or c.rationale.replace("\n", " ")
        score = f"{c.score:.3f}" if c.score is not None else "—"
        lines.append(f"| {c.id} | {c.parent or '—'} | {c.status} | {score} | {note.replace('|', '／')[:120]} |")
    if result.heldout:
        lines += ["", "heldout の点数：" + "、".join(f"{key} {value:.3f}" for key, value in result.heldout.items())]
    if best is not base:
        lines += ["", f"## 今の版と {best.id} の差分", "", "```diff", diff(base.prompt, best.prompt).rstrip(), "```"]
    return "\n".join(lines) + "\n"


def promote(run_folder: Path, candidate_id: str | None = None, force: bool = False, root: Path = prompt_store.PROMPTS_DIR) -> str:
    """人が差分を読んだうえで実行する。推薦されていない候補は force がなければ昇格しない。"""
    summary = json.loads((run_folder / "run.json").read_text(encoding="utf-8"))
    candidate_id = candidate_id or summary["best"]
    if not force and (summary["decision"] != RECOMMENDED or candidate_id != summary["best"]):
        raise ValueError(f"{candidate_id} は推薦されていません（判定：{summary['decision']}）。昇格するなら --force")
    text = (run_folder / "candidates" / f"{candidate_id}.md").read_text(encoding="utf-8")
    name = prompt_store.add_version(summary["target"], text, root)
    prompt_store.set_active(summary["target"], name, root)
    return name

