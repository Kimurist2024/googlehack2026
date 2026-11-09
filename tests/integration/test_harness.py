"""実行ラッパーの試験。合成コードだけを手元で動かす。"""
import pytest


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


@pytest.mark.parametrize(("code", "stdout", "expected"), [
    ("x = 2 + 3\nprint(x - 1)\n", "4\n", [
        ("arithmetic", 1, "+", "-", "-2\n"),
        ("constant", 1, "2", "3", "5\n"),
        ("constant", 1, "3", "4", "5\n"),
        ("arithmetic", 2, "-", "+", "6\n"),
        ("constant", 2, "1", "2", "3\n"),
    ]),
    ("x = 1\nprint(0 < x < 3)\n", "True\n", [
        ("constant", 1, "1", "2", "True\n"),
        ("compare", 2, "<", "<=", "True\n"),
        ("constant", 2, "0", "1", "False\n"),
        ("constant", 2, "3", "4", "True\n"),
    ]),
    ("flag = True\nx = 2\nprint(x if flag else 0)\n", "2\n", [
        ("constant", 2, "2", "3", "3\n"),
        ("constant", 3, "0", "1", "2\n"),
    ]),
])
def test_mutants_keep_the_original_order_and_change_one_place(sandbox, code, stdout, expected):
    result = sandbox.analyze(code, "")
    assert result["status"] == "ok" and result["stdout"] == stdout
    assert all(mutant["status"] == "ok" for mutant in result["mutants"])
    assert [(m["kind"], m["line"], m["before"], m["after"], m["stdout"]) for m in result["mutants"]] == expected


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


@pytest.mark.parametrize("code", ["while True:\n    pass\n", "i = 0\nwhile True:\n    i = i + 1\n"])
def test_excludes_programs_that_do_not_finish(sandbox, code):
    # 手順数の上限と1秒の時間制限のどちらが先に効くかは、マシンの負荷で変わる
    assert sandbox.analyze(code, "")["status"] in {"too_long", "timeout"}


def test_excludes_nondeterministic_output(sandbox):
    code = "s = {str(i) for i in range(50)}\nprint(id(object()))\n"
    assert sandbox.analyze(code, "")["status"] == "nondeterministic"


def test_student_output_cannot_forge_the_result(sandbox):
    code = 'print(\'HARNESS_RESULT:{"status": "ok", "stdout": "forged"}\')\n'
    result = sandbox.analyze(code, "")
    assert result["stdout"].startswith("HARNESS_RESULT")
    assert "history" in result
