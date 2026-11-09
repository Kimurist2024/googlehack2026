"""校正済みの説明（proofread.json）で、評価用の模擬提出物（cases_persona）を仕上げる。合成データ専用。

proofread.json は {case_id: [主張の文, ...]}。文の数と順番は drafts.jsonl の claims と同じ。
使わない提出物は {case_id: null}。主張の正解ラベルと確かめ方（check）は下書きのまま使う。

cd apps/api && ../../.venv/bin/python evals/cases_persona/_make/finalize.py
"""
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from personas import BY_ID  # noqa: E402

END = "。！？!?"


def sentence(text: str) -> str:
    text = text.strip()
    return text if text and text[-1] in END else text + "。"


def main() -> None:
    drafts = [json.loads(line) for line in open(HERE / "drafts.jsonl", encoding="utf-8")]
    voiced = {}
    if (HERE / "voice_out.jsonl").exists():
        voiced = {json.loads(line)["key"]: json.loads(line)["model"] for line in open(HERE / "voice_out.jsonl", encoding="utf-8")}
    proof = json.loads((HERE / "proofread.json").read_text(encoding="utf-8"))
    for old in ROOT.iterdir():
        if old.is_dir() and old.name != "_make":
            shutil.rmtree(old)
    made, dropped = 0, 0
    for d in drafts:
        texts = proof.get(d["case_id"], "missing")
        if texts == "missing":
            raise SystemExit(f"{d['case_id']} の校正がありません")
        if texts is None:
            dropped += 1
            continue
        if len(texts) != len(d["claims"]):
            raise SystemExit(f"{d['case_id']}: 文の数が主張と合いません")
        folder = ROOT / d["case_id"]
        folder.mkdir()
        (folder / "program.py").write_text(d["code"], encoding="utf-8")
        (folder / "explanation.txt").write_text("".join(sentence(t) for t in texts) + "\n", encoding="utf-8")
        persona = BY_ID[d["persona"]]
        gold = {
            "split": d["split"],
            "goal": d["goal"],
            "persona": d["persona"],
            "source": f"{d['model']} に{persona['name']}の癖を指示して書かせた {d['task_id']} のコード（クセを取ったもの）と、"
                      f"型から作った説明を {voiced.get(d['case_id'], 'モデル')} が口調を書き直し、人が校正したもの（合成データ）",
            "claims": [
                {"id": f"g{i}", "text": t.strip().rstrip("。"), "label": c["label"], "kind": c["kind"], "evidence": c["evidence"]}
                | ({"check": c["check"]} if "check" in c else {})
                for i, (t, c) in enumerate(zip(texts, d["claims"]), 1)
            ],
        }
        (folder / "gold.json").write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        made += 1
    print("cases:", made, "dropped:", dropped)


if __name__ == "__main__":
    main()
