"""動きの主張を確かめる実行の試験。合成コードだけを手元で動かす。"""
import pytest

from evalh.behavior import ProbingFinder
from evalh.cases import load_cases
from evalh.fakes import LexiconFinder, SentenceDecomposer, TemplateWriter
from evalh.pipeline import StagedPipeline
from evalh.runner import evaluate
from qgen.probes import PatternProbePlanner

AVERAGE = "def average(nums):\n    total = 0\n    for n in nums:\n        total += n\n    return total / len(nums)\n\nprint(average([3, 4, 8]))\n"


def call(function, args):
    return {"kind": "call", "function": function, "args": args}


def test_calls_a_function_with_literal_arguments(sandbox):
    result = sandbox.probe(AVERAGE, [call("average", "[[]]"), call("average", "[[2, 4]]")])
    assert result["status"] == "ok"
    assert result["probes"] == [{"status": "ok", "raised": "ZeroDivisionError"}, {"status": "ok", "returned": "3.0"}]


def test_call_does_not_run_top_level_code(sandbox):
    code = "LIMIT = 3\ndef f(x):\n    return x + LIMIT\n\nwhile True:\n    pass\n"
    assert sandbox.probe(code, [call("f", "[1]")])["probes"] == [{"status": "ok", "returned": "4"}]


@pytest.mark.parametrize(
    "code",
    [
        "def f(x):\n    return open('/etc/hosts').read()\n",
        "def f(x):\n    return ().__class__.__mro__\n",
        "def f(x):\n    return getattr(x, 'real')\n",
    ],
)
def test_probe_refuses_the_same_code_as_analyze(sandbox, code):
    """関数を呼ぶだけの確認でも、実行と同じく使えない名前を含むコードは動かさない。"""
    result = sandbox.probe(code, [call("f", "[1]")])
    assert result["status"] == "unsupported_code"


def _load(source):
    namespace = {"__name__": "harness_under_test"}
    exec(compile(source, "harness.py", "exec"), namespace)
    return namespace


def test_probe_child_gets_no_environment_and_cpu_limit(monkeypatch):
    """関数を呼ぶ子プロセスには親の環境変数を渡さず、資源の上限を先にかける。"""
    import subprocess
    import types

    from qgen.sandbox import HARNESS_SOURCE

    # 実行ラッパーは読み込むと main() が動くので、最後の呼び出しを除いて読み込む
    harness = types.SimpleNamespace(**_load(HARNESS_SOURCE.rsplit("main()", 1)[0]))
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(kwargs, args=args)
        raise subprocess.TimeoutExpired(args, 1)

    monkeypatch.setenv("SESSION_SECRET", "do-not-leak")
    monkeypatch.setattr(subprocess, "run", fake_run)
    request = {"run_timeout_sec": 1, "deadline_sec": 5, "max_probes": 1, "probes": [call("f", "[1]")]}
    assert harness.probe("def f(x):\n    return x\n", request)["probes"] == [{"status": "timeout"}]
    assert seen["env"] == harness.CHILD_ENV and seen["args"][-1] == "2"
    assert harness.PROBER.startswith(harness.LIMITS)


def test_runs_the_whole_program_and_returns_output(sandbox):
    code = "n = 3\nwhile n > 0:\n    print(n)\n    n = n - 1\n"
    result = sandbox.probe(code, [{"kind": "run", "stdin": ""}])
    assert result["probes"][0]["status"] == "ok"
    assert result["probes"][0]["stdout"].split() == ["3", "2", "1"]


@pytest.mark.parametrize(
    ("probe", "status"),
    [
        (call("missing", "[1]"), "no_function"),
        (call("average", "[__import__('os')]"), "bad_probe"),
        (call("average", "1"), "bad_probe"),
        ({"kind": "shell"}, "bad_probe"),
    ],
)
def test_rejects_probes_it_cannot_run_safely(sandbox, probe, status):
    assert sandbox.probe(AVERAGE, [probe])["probes"] == [{"status": status}]


def test_function_that_never_returns_times_out(sandbox):
    code = "def spin(x):\n    while True:\n        x += 1\n"
    assert sandbox.probe(code, [call("spin", "[0]")])["probes"] == [{"status": "timeout"}]


def test_probe_obeys_import_rules_and_limits(sandbox):
    assert sandbox.probe("import os\ndef f():\n    return 1\n", [call("f", "[]")])["status"] == "unsupported_import"
    assert len(sandbox.probe(AVERAGE, [call("average", "[[1]]")] * 10)["probes"]) == 3


def test_probing_finds_behavior_gaps_in_the_dev_cases(sandbox):
    finder = ProbingFinder(LexiconFinder(), PatternProbePlanner(), sandbox)
    pipeline = StagedPipeline("probe", SentenceDecomposer(), finder, TemplateWriter())
    dev = load_cases(split="dev")
    report = evaluate(pipeline, dev)
    behavior_gaps = {(case.id, claim.text) for case in dev for claim in case.claims if claim.kind == "behavior"}
    missed = {(f["case_id"], f["gold_claim"]) for f in report["failures"] if f["kind"] == "missed_gap"}
    assert behavior_gaps and not behavior_gaps & missed
    assert {entry["verdict"] for entry in finder.log} == {"fails"}
