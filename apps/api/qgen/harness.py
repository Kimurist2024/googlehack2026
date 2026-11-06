"""隔離環境の中で動く実行ラッパー。標準ライブラリだけで動かす。

Code Execution は渡したコードを ``exec`` で動かすので、``__file__`` には頼らない。
作業フォルダに ``student.py`` と ``request.json`` がある前提で、結果を JSON 1行で標準出力に書く。
生徒のコードは別プロセスで動かし、作業は一時フォルダで行って最後に消す。

隔離そのものは Code Execution が担う。ここでの検査と制限は、その内側に重ねる多層防御で、
使える組み込み関数と属性を絞り、子プロセスには環境変数を渡さず、メモリやファイルの大きさにも上限を設ける。
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
# 授業の課題では使わず、隔離を破る手がかりになる組み込み関数と名前
BLOCKED_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "breakpoint", "memoryview", "help",
    "__builtins__", "__loader__", "__spec__",
}
# 子プロセスに渡す環境変数。親の環境（認証情報など）は引き継がない
CHILD_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
SWAP = {
    ast.Lt: (ast.LtE, "<", "<="),
    ast.LtE: (ast.Lt, "<=", "<"),
    ast.Gt: (ast.GtE, ">", ">="),
    ast.GtE: (ast.Gt, ">=", ">"),
    ast.Eq: (ast.NotEq, "==", "!="),
    ast.NotEq: (ast.Eq, "!=", "=="),
}

# 生徒のコードを読む前に、子プロセス自身に資源の上限をかける（メモリ512MB、ファイル8MB、CPU時間）。
# 下げた上限は戻せず、resource も import できないので、生徒のコードからは外せない。
# preexec_fn はスレッドのある親では安全でないので使わない
TRACER = r'''
import json, sys
path, out, max_events, cpu_sec = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
try:
    import resource
    for kind, value in ((resource.RLIMIT_AS, 512 * 1024 * 1024), (resource.RLIMIT_FSIZE, 8 * 1024 * 1024),
                        (resource.RLIMIT_CORE, 0), (resource.RLIMIT_CPU, cpu_sec)):
        try:
            resource.setrlimit(kind, (value, value))
        except (ValueError, OSError):
            pass
except ImportError:
    pass
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


def blocked_of(tree):
    """使えない名前と、__class__ のような特殊な属性の参照を集める。"""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in BLOCKED_NAMES:
            names.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            names.add("." + node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in BLOCKED_NAMES:
            names.add(node.name)
    return names


def mutants_of(tree, limit):
    """比較演算子、+ と -、整数定数を1か所ずつ変えたコードを作る。"""
    found = []
    nodes = list(ast.walk(tree))
    for index, node in enumerate(nodes):
        line = getattr(node, "lineno", 0)
        changes = []
        if isinstance(node, ast.Compare) and type(node.ops[0]) in SWAP:
            changes.append(("compare", SWAP[type(node.ops[0])]))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            is_add = isinstance(node.op, ast.Add)
            changes.append(("arithmetic", (ast.Sub if is_add else ast.Add, "+" if is_add else "-", "-" if is_add else "+")))
        elif isinstance(node, ast.Constant) and type(node.value) is int:
            changes.append(("constant", (None, str(node.value), str(node.value + 1))))
        for kind, (new_type, before, after) in changes:
            copied = copy.deepcopy(tree)
            target = list(ast.walk(copied))[index]
            if kind == "compare":
                target.ops[0] = new_type()
            elif kind == "arithmetic":
                target.op = new_type()
            else:
                target.value = target.value + 1
            found.append({"kind": kind, "line": line, "before": before, "after": after, "source": ast.unparse(copied)})
            if len(found) >= limit:
                return found
    return found


def run_program(folder, source, stdin, request):
    path = os.path.join(folder, "program.py")
    trace_path = os.path.join(folder, "trace.json")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
    if os.path.exists(trace_path):
        os.remove(trace_path)
    cpu_sec = int(request["run_timeout_sec"]) + 1
    try:
        done = subprocess.run(
            [sys.executable, "-I", os.path.join(folder, "tracer.py"), path, trace_path, str(request["max_events"]), str(cpu_sec)],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=request["run_timeout_sec"],
            cwd=folder,
            env=CHILD_ENV,
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
    unsafe = sorted(blocked_of(tree))
    if unsafe:
        return {"status": "unsupported_code", "detail": ",".join(unsafe)}

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
