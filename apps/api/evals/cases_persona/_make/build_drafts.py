"""ペルソナごとに書かせたコードから、説明の下書き（drafts.jsonl）と口調の書き直しの仕事（voice_jobs.json）を作る。合成データ専用。

コードの掃除、主張の値（思い込み）、正解ラベル（実行して決める）は cases_lowq2/_make/build.py と同じ。
違うのは、計算違いの割合と主張の数をペルソナから取ること、同じ課題でペルソナを散らして選ぶこと。
説明の文はまだ型のまま。voice_jobs.json をモデルに口調で書き直させ、人が校正して finalize.py で仕上げる。

cd apps/api && APP_ENV=local ALLOW_LOCAL_SANDBOX=1 PYTHONPATH=. ../../.venv/bin/python evals/cases_persona/_make/build_drafts.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "cases_lowq2" / "_make"))
import build as B  # noqa: E402
import tasks2  # noqa: E402
from personas import BY_ID  # noqa: E402
from qgen import probes as P  # noqa: E402

rng = B.rng
MAX_PER_TASK = 3
VOICE_MODELS = [
    "sbintuitions/sarashina2.2-3b-instruct-v0.1",
    "llm-jp/llm-jp-3-3.7b-instruct",
    "SakanaAI/TinySwallow-1.5B-Instruct",
]

VOICE_PROMPT = """あなたはプログラミングを習い始めた高校生です。下のプログラムを自分で書きました。
先生に出す「プログラムの説明」を、次の口調で書いてください。
口調: {voice}

下の各文を、意味を変えずにその口調で言い換えてください。
- 文の数と順番はそのまま。1行に1文で、行の頭に「1.」のように番号をつける。
- 入力の値（数・文字列・リスト）と、結果（返す値・表示されるもの・エラーになるかどうか）は変えない。省いたり、別の値を足したりしない。
- 言い換えた文のほかは何も書かない（あいさつ・まとめ・コードは書かない）。

プログラム:
```python
{code}```

文:
{claims}"""


def pick(items):
    """バグの出方（signature）とペルソナが重ならないように、最大 MAX_PER_TASK 件を選ぶ。"""
    rng.shuffle(items)
    items.sort(key=lambda it: -sum(s is False for s in it[2]))
    chosen, sigs, personas, models = [], set(), set(), {}
    for it in items:
        row = it[0]
        if it[2] in sigs or row["persona"] in personas or models.get(row["model"], 0) >= 2:
            continue
        chosen.append(it)
        sigs.add(it[2])
        personas.add(row["persona"])
        models[row["model"]] = models.get(row["model"], 0) + 1
        if len(chosen) == MAX_PER_TASK:
            break
    return chosen


def main() -> None:
    rows = [json.loads(line) for line in open(HERE / "code_out.jsonl", encoding="utf-8")]
    tasks = {t["id"]: t for t in tasks2.TASKS}
    stats: dict[str, int] = {}
    pool: dict[str, list] = {t: [] for t in tasks}
    seen = set()
    for row in rows:
        task = tasks[row["task_id"]]
        source = B.code_of(row["reply"])
        code, why = B.clean(source, task) if source else (None, "no_code")
        if code and code in seen:
            why, code = "duplicate", None
        stats[why] = stats.get(why, 0) + 1
        if not code:
            continue
        seen.add(code)
        signature = tuple(B.matches_ref(code, task, spec) for spec in task["claims"])
        if all(s is None for s in signature):
            stats["all_unknown"] = stats.get("all_unknown", 0) + 1
            continue
        pool[task["id"]].append((row, code, signature))
    print("filter:", stats)

    drafts, total = [], {"correct": 0, "gap": 0, "structure": 0}
    for task_id, items in pool.items():
        task = tasks[task_id]
        for n, (row, code, signature) in enumerate(pick(items), 1):
            persona = BY_ID[row["persona"]]
            B.WRONG_RATE = persona["wrong"]
            specs = [s for s, ok in zip(task["claims"], signature) if ok is not None]
            rng.shuffle(specs)
            behaviors = []
            for spec in specs[: rng.choice(persona["claims"])]:
                texts, probe = B.belief(task, spec)
                outcome = B.verdict(code, probe)
                if outcome == P.UNKNOWN:
                    continue
                behaviors.append((B.render(rng.choice(texts)), "correct" if outcome == P.HOLDS else "gap", probe))
            if not behaviors:
                continue
            claims = [{"text": t, "label": "correct", "kind": "structure", "evidence": e} for t, e in B.structure_claims(code, task)]
            claims += [{"text": t, "label": label, "kind": "behavior",
                        "evidence": B.behavior_evidence(code, task) if label == "correct" else [], "check": vars(probe)}
                       for t, label, probe in behaviors]
            drafts.append({"case_id": f"{task_id}_{row['persona']}", "task_id": task_id, "persona": row["persona"],
                           "model": row["model"], "split": "heldout" if task_id in tasks2.HELDOUT else "dev",
                           "goal": task["goal"], "code": code, "claims": claims})
            for c in claims:
                total["structure" if c["kind"] == "structure" else c["label"]] += 1
    with open(HERE / "drafts.jsonl", "w", encoding="utf-8") as out:
        for d in drafts:
            out.write(json.dumps(d, ensure_ascii=False) + "\n")
    jobs = [{"key": d["case_id"], "task_id": d["task_id"], "persona": d["persona"], "model": VOICE_MODELS[i % len(VOICE_MODELS)],
             "prompt": VOICE_PROMPT.format(voice=BY_ID[d["persona"]]["voice"], code=d["code"],
                                           claims="\n".join(f"{k}. {c['text']}" for k, c in enumerate(d["claims"], 1)))}
            for i, d in enumerate(drafts)]
    (HERE / "voice_jobs.json").write_text(json.dumps(jobs, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    personas = {}
    for d in drafts:
        personas[d["persona"]] = personas.get(d["persona"], 0) + 1
    print("cases:", len(drafts), total, personas)


if __name__ == "__main__":
    main()
