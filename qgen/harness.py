"""隔離環境の中で動く実行ラッパー。標準ライブラリだけで動かす。

Code Execution は渡したコードを ``exec`` で動かすので、``__file__`` には頼らない。
作業フォルダに ``student.py`` と ``request.json`` がある前提で、結果を JSON 1行で標準出力に書く。
生徒のコードは別プロセスで動かし、作業は一時フォルダで行って最後に消す。
"""
import ast
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

RESULT_PREFIX = "HARNESS_RESULT:"
ALLOWED_IMPORTS = {"math", "statistics", "string", "collections", "itertools", "functools", "fractions", "decimal"}
SWAP = {
    ast.Lt: (ast.LtE, "<", "<="),
    ast.LtE: (ast.Lt, "<=", "<"),
    ast.Gt: (ast.GtE, ">", ">="),
    ast.GtE: (ast.Gt, ">=", ">"),
    ast.Eq: (ast.NotEq, "==", "!="),
    ast.NotEq: (ast.Eq, "!=", "=="),
}

TRACER = r'''
import json, sys
path, out, max_events = sys.argv[1], sys.argv[2], int(sys.argv[3])
code = compile(open(path, encoding="utf-8").read(), path, "exec")
history, last, previous, count = [], {}, {}, [0]
SIMPLE = (int, float, str, bool)

def record(frame, line):
    scope = "" if frame.f_code.co_name == "<module>" else frame.f_code.co_name
    for name, value in list(frame.f_locals.items()):
        if name.startswith("__") or not isinstance(value, SIMPLE):
            continue
        key = (id(frame), name)
        if key not in last or last[key] != value or type(last[key]) is not type(value):
            last[key] = value
            if len(history) < 2000:
                history.append({"scope": scope, "name": name, "value": repr(value), "line": line})

def tracer(frame, event, arg):
    if frame.f_code.co_filename != path:
        return None
    if event in ("line", "return"):
        count[0] += 1
        if count[0] > max_events:
            raise SystemExit(99)
        record(frame, previous.get(id(frame), frame.f_lineno))
        if event == "line":
            previous[id(frame)] = frame.f_lineno
    return tracer

sys.settrace(tracer)
try:
    exec(code, {"__name__": "__main__"})
finally:
    sys.settrace(None)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(history, handle)
'''


def imports_of(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    return names


def _mutation_sites(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and type(node.ops[0]) in SWAP:
            yield node, "compare", SWAP[type(node.ops[0])]
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            is_add = isinstance(node.op, ast.Add)
            yield node, "arithmetic", (ast.Sub if is_add else ast.Add, "+" if is_add else "-", "-" if is_add else "+")
        elif isinstance(node, ast.Constant) and type(node.value) is int:
            yield node, "constant", (None, str(node.value), str(node.value + 1))


def mutants_of(tree, limit):
    """比較演算子、+ と -、整数定数を1か所ずつ変えたコードを作る。"""
    sites = []
    for site in _mutation_sites(tree):
        sites.append(site)
        if len(sites) >= limit:
            break
    if not sites:
        return []
    # 木と対象ノードを同時に1回だけコピーし、元の木には触れない。
    copied, sites = copy.deepcopy((tree, sites))
    found = []
    for target, kind, (new_type, before, after) in sites:
        if kind == "compare":
            original = target.ops[0]
            target.ops[0] = new_type()
        elif kind == "arithmetic":
            original = target.op
            target.op = new_type()
        else:
            original = target.value
            target.value += 1
        try:
            source = ast.unparse(copied)
        finally:
            # 例外時にも戻す。次の候補に前の変更を持ち越さない。
            if kind == "compare":
                target.ops[0] = original
            elif kind == "arithmetic":
                target.op = original
            else:
                target.value = original
        found.append({"kind": kind, "line": getattr(target, "lineno", 0), "before": before, "after": after, "source": source})
    return found


def run_program(folder, source, stdin, request):
    path = os.path.join(folder, "program.py")
    trace_path = os.path.join(folder, "trace.json")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
    if os.path.exists(trace_path):
        os.remove(trace_path)
    try:
        done = subprocess.run(
            [sys.executable, "-I", os.path.join(folder, "tracer.py"), path, trace_path, str(request["max_events"])],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=request["run_timeout_sec"],
            cwd=folder,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "stdout": "", "history": []}
    if done.returncode == 99:
        return {"status": "too_long", "stdout": "", "history": []}
    if done.returncode != 0:
        return {"status": "error", "stdout": done.stdout[-2000:], "stderr": done.stderr[-300:], "history": []}
    if len(done.stdout) > request["max_output_chars"]:
        return {"status": "too_much_output", "stdout": "", "history": []}
    history = []
    try:
        with open(trace_path, encoding="utf-8") as handle:
            history = json.load(handle)
    except (OSError, ValueError):
        return {"status": "error", "stdout": done.stdout, "stderr": "trace unavailable", "history": []}
    return {"status": "ok", "stdout": done.stdout, "history": history}


def analyze(source, request):
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return {"status": "syntax_error", "detail": "line %s" % error.lineno}
    blocked = sorted(name for name in imports_of(tree) if name not in ALLOWED_IMPORTS)
    if blocked:
        return {"status": "unsupported_import", "detail": ",".join(blocked)}

    deadline = time.monotonic() + request["deadline_sec"]
    folder = tempfile.mkdtemp(prefix="run-")
    try:
        with open(os.path.join(folder, "tracer.py"), "w", encoding="utf-8") as handle:
            handle.write(TRACER)
        stdin = request["stdin"]
        first = run_program(folder, source, stdin, request)
        if first["status"] != "ok":
            return {"status": first["status"], "detail": first.get("stderr", "")}
        second = run_program(folder, source, stdin, request)
        if second["status"] != "ok" or second["stdout"] != first["stdout"]:
            return {"status": "nondeterministic", "detail": ""}
        results = []
        for mutant in mutants_of(tree, request["max_mutants"]):
            if time.monotonic() > deadline:
                break
            run = run_program(folder, mutant.pop("source"), stdin, request)
            results.append({**mutant, "status": run["status"], "stdout": run["stdout"][-500:]})
        return {"status": "ok", "stdout": first["stdout"], "history": first["history"], "mutants": results}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def main():
    with open("request.json", encoding="utf-8") as handle:
        request = json.load(handle)
    with open("student.py", encoding="utf-8") as handle:
        source = handle.read()
    print(RESULT_PREFIX + json.dumps(analyze(source, request), ensure_ascii=False))


main()
