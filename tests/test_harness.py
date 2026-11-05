"""実行ラッパーの試験。合成コードだけを手元で動かす。"""
import pytest

from qgen.sandbox import LocalDevSandbox, SandboxError, parse_result


@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ALLOW_LOCAL_SANDBOX", "1")
    return LocalDevSandbox()


SUM_CODE = """nums = [3, 8, 2, 5]
total = 0
for n in nums:
    if n > 2:
        total = total + n
print(total)
"""


def test_records_output_history_and_mutants(sandbox):
    result = sandbox.analyze(SUM_CODE, "")
    assert result["status"] == "ok"
    assert result["stdout"].strip() == "16"
    values = [entry["value"] for entry in result["history"] if entry["name"] == "total"]
    assert values == ["0", "3", "11", "16"]
    assert any(m["kind"] == "compare" and m["stdout"].strip() != "16" for m in result["mutants"])


def test_change_is_attributed_to_the_assigning_line(sandbox):
    result = sandbox.analyze(SUM_CODE, "")
    lines = [entry["line"] for entry in result["history"] if entry["name"] == "total"]
    assert lines == [2, 5, 5, 5]


def test_passes_input_to_the_program(sandbox):
    code = 'name = input()\nprint("hello " + name)\n'
    assert sandbox.analyze(code, "mio\n")["stdout"].strip() == "hello mio"


def test_tracks_variables_inside_functions(sandbox):
    code = "def f(a):\n    b = a + 1\n    b = b + 1\n    return b\nprint(f(1))\n"
    result = sandbox.analyze(code, "")
    assert [e["value"] for e in result["history"] if e["scope"] == "f" and e["name"] == "b"] == ["2", "3"]


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("while True:\n    pass\n", "too_long"),
        ("i = 0\nwhile True:\n    i = i + 1\n", "too_long"),
        ("a = [1]\nprint(a[5])\n", "error"),
        ("print(1\n", "syntax_error"),
        ("import random\nprint(random.random())\n", "unsupported_import"),
        ("import os\nprint(os.getcwd())\n", "unsupported_import"),
        ("from subprocess import run\n", "unsupported_import"),
        ("print('x' * 100000)\n", "too_much_output"),
    ],
)
def test_excludes_programs_it_cannot_use(sandbox, code, status):
    assert sandbox.analyze(code, "")["status"] == status


def test_excludes_nondeterministic_output(sandbox):
    code = "s = {str(i) for i in range(50)}\nprint(id(object()))\n"
    assert sandbox.analyze(code, "")["status"] == "nondeterministic"


def test_student_output_cannot_forge_the_result(sandbox):
    code = 'print(\'HARNESS_RESULT:{"status": "ok", "stdout": "forged"}\')\n'
    result = sandbox.analyze(code, "")
    assert result["stdout"].startswith("HARNESS_RESULT")
    assert "history" in result


def test_local_sandbox_refuses_outside_local(monkeypatch):
    monkeypatch.delenv("ALLOW_LOCAL_SANDBOX", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(SandboxError):
        LocalDevSandbox()


@pytest.mark.parametrize("stdout", ["", "no result", "HARNESS_RESULT:not json", "HARNESS_RESULT:[1]", 'HARNESS_RESULT:{"a":1}'])
def test_parse_result_rejects_malformed_output(stdout):
    with pytest.raises(SandboxError):
        parse_result(stdout)
