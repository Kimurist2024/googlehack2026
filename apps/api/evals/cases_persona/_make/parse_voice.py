"""モデルが口調を書き直した説明（voice_out.jsonl）を、主張ごとの文に分けて校正の下書きにする。合成データ専用。

出力:
- proofread_draft.json: {case_id: [文, ...]}。文の数が合わない・書き直しがないときは型の文のまま
- review.txt: 人が校正するための一覧。値が消えた・増えたと疑われる文に印（!）を付ける

人はこれを読み、proofread.json（finalize.py が読む）を作る。
"""
import ast
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
NUMBERED = re.compile(r"^\s*(\d+)[\.．、)）]\s*(.+?)\s*$")


def lines_of(reply: str) -> list[str]:
    out = {}
    for line in reply.splitlines():
        m = NUMBERED.match(line)
        if m and int(m.group(1)) not in out:
            out[int(m.group(1))] = m.group(2)
    return [out[k] for k in sorted(out)] if out and sorted(out) == list(range(1, len(out) + 1)) else []


def values(check: dict) -> set[str]:
    """主張に出てくるはずの値（数と文字列）。"""
    found = set()
    texts = [check.get("expect_value", ""), check.get("args", ""), check.get("stdin", "")]
    for text in texts:
        try:
            node = ast.parse(text, mode="eval")
            for n in ast.walk(node):
                if isinstance(n, ast.Constant) and not isinstance(n.value, bool) and n.value is not None:
                    found.add(str(n.value))
        except SyntaxError:
            found.update(text.split())
    return {v for v in found if v.strip()}


def lost_values(claim: dict, text: str) -> list[str]:
    """型の文にあった値のうち、書き直しで消えたもの。"""
    if "check" not in claim:
        return []
    return [v for v in values(claim["check"]) if v not in text and v in claim["text"]]


def main() -> None:
    drafts = [json.loads(line) for line in open(HERE / "drafts.jsonl", encoding="utf-8")]
    replies = {}
    for line in open(HERE / "voice_out.jsonl", encoding="utf-8"):
        row = json.loads(line)
        replies.setdefault(row["key"], []).append(row["reply"])
    proof, report = {}, []
    for d in drafts:
        claims = d["claims"]
        candidates = [ls for ls in (lines_of(r) for r in replies.get(d["case_id"], [])) if len(ls) == len(claims)]
        # 値の消えた文が少ない書き直しを選ぶ
        candidates.sort(key=lambda ls: sum(len(lost_values(c, t)) for c, t in zip(claims, ls)))
        chosen = candidates[0] if candidates else [c["text"] for c in claims]
        proof[d["case_id"]] = chosen
        report.append(f"## {d['case_id']} [{d['persona']}] {d['split']} {'' if candidates else '(書き直しなし)'}")
        for k, (c, t) in enumerate(zip(claims, chosen), 1):
            mark = ""
            lost = lost_values(c, t)
            mark = f" !消えた値 {lost}" if lost else ""
            check = c.get("check")
            how = f"{check['expect_kind']} {check['expect_value']} args={check['args']} stdin={check['stdin']!r}" if check else "structure"
            report.append(f"{k}. [{c['label']}] {how}{mark}\n   型: {c['text']}\n   声: {t}")
    (HERE / "proofread_draft.json").write_text(json.dumps(proof, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (HERE / "review.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("cases:", len(drafts), "without voice:", sum(1 for line in report if "(書き直しなし)" in line), "flags:", sum("!消えた値" in line for line in report))


if __name__ == "__main__":
    main()
