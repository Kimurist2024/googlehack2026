"""evals/cases_lowq2 の動きの主張の正解が、今のコードを動かした結果と合っているか。合成コードだけを手元で動かす。"""
import json

import pytest

from evalh.cases import DEFAULT_DIR
from qgen import probes

FOLDER = DEFAULT_DIR.parent / "cases_lowq2"
CASES = sorted(p for p in FOLDER.iterdir() if (p / "gold.json").exists())


@pytest.mark.parametrize("folder", CASES, ids=[p.name for p in CASES])
def test_gold_labels_match_execution(folder, sandbox):
    code = (folder / "program.py").read_text(encoding="utf-8")
    claims = [c for c in json.loads((folder / "gold.json").read_text(encoding="utf-8"))["claims"] if c["kind"] == "behavior"]
    planned = [probes.Probe(**c["check"]) for c in claims]
    verdicts = []
    for start in range(0, len(planned), probes.MAX_PROBES):  # 1回に動かせるのは MAX_PROBES 件まで
        chunk = planned[start:start + probes.MAX_PROBES]
        result = sandbox.probe(code, [p.request() for p in chunk])
        verdicts += [probes.verdict(p, o) for p, o in zip(chunk, result["probes"])]
    assert verdicts == [probes.HOLDS if c["label"] == "correct" else probes.FAILS for c in claims]
