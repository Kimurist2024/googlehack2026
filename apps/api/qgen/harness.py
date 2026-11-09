"""隔離環境の中で動く実行ラッパー。標準ライブラリだけで動かす。

Code Execution は渡したコードを ``exec`` で動かすので、``__file__`` には頼らない。
作業フォルダに ``student.py`` と ``request.json`` がある前提で、結果を JSON 1行で標準出力に書く。
生徒のコードは別プロセスで動かし、作業は一時フォルダで行って最後に消す。

request.json の mode が "probe" のときは、生徒の説明の「動き」についての主張を確かめる。
関数を1つ呼ぶ（call）か、プログラム全体を動かす（run）。引数はリテラルだけを受け付ける。

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
# preexec_fn はスレッドのある親では安全でないので使わない。CPU 時間は最後の引数で受け取る。
# 実行（TRACER）と主張の確認（PROBER）の両方の先頭に置く
LIMITS = r'''
import sys
try:
    import resource
    for kind, value in ((resource.RLIMIT_AS, 512 * 1024 * 1024), (resource.RLIMIT_FSIZE, 8 * 1024 * 1024),
                        (resource.RLIMIT_CORE, 0), (resource.RLIMIT_CPU, int(sys.argv[-1]))):
        try:
            resource.setrlimit(kind, (value, value))
        except (ValueError, OSError):
            pass
except ImportError:
    pass
'''
TRACER = LIMITS + r'''
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


# 関数を1つ呼ぶ。最上位の文は、関数の定義・import・リテラルの代入だけを残し、それ以外は動かさない。
PROBER = LIMITS + r'''
import ast, json, sys
path, spec_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(spec_path, encoding="utf-8") as handle:
    spec = json.load(handle)
with open(path, encoding="utf-8") as handle:
    tree = ast.parse(handle.read())

def is_literal(node):
    try:
        ast.literal_eval(node)
        return True
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False

keep = [
    node for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.Import, ast.ImportFrom))
    or (isinstance(node, ast.Assign) and is_literal(node.value))
]
namespace = {"__name__": "__probe__"}
exec(compile(ast.Module(body=keep, type_ignores=[]), path, "exec"), namespace)
args = ast.literal_eval(spec["args"])
result = {"status": "ok"}
try:
    result["returned"] = repr(namespace[spec["function"]](*args))[:500]
except RecursionError:
    result["raised"] = "RecursionError"
except Exception as error:
    result["raised"] = type(error).__name__
with open(out_path, "w", encoding="utf-8") as handle:
    json.dump(result, handle)
'''
MAX_ARGS_CHARS = 200
# 呼び出し側（qgen/probes.py の MAX_PROBES）が指定しなかったときの、主張の確認の件数
DEFAULT_MAX_PROBES = 3
# 結果に残す出力の長さ（どれも末尾から）
STDOUT_TAIL = 2000
STDERR_TAIL = 300
MUTANT_STDOUT_TAIL = 500


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


def cpu_seconds(request):
    return int(request["run_timeout_sec"]) + 1


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def static_check(source):
    """動かす前の検査（構文、import、使えない名前）。通れば (構文木, None)、通らなければ (None, 結果)。"""
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return None, {"status": "syntax_error", "detail": "line %s" % error.lineno}
    blocked = sorted(name for name in imports_of(tree) if name not in ALLOWED_IMPORTS)
    if blocked:
        return None, {"status": "unsupported_import", "detail": ",".join(blocked)}
    unsafe = sorted(blocked_of(tree))
    if unsafe:
        return None, {"status": "unsupported_code", "detail": ",".join(unsafe)}
    return tree, None


def run_child(folder, script, args, stdin, request):
    """作業フォルダの script を子プロセスで動かす。環境変数は渡さず、CPU 時間は最後の引数で渡す。"""
    return subprocess.run(
        [sys.executable, "-I", os.path.join(folder, script), *args, str(cpu_seconds(request))],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=request["run_timeout_sec"],
        cwd=folder,
        env=CHILD_ENV,
    )


def run_program(folder, source, stdin, request):
    path = os.path.join(folder, "program.py")
    trace_path = os.path.join(folder, "trace.json")
    write_text(path, source)
    if os.path.exists(trace_path):
        os.remove(trace_path)
    try:
        done = run_child(folder, "tracer.py", [path, trace_path, str(request["max_events"])], stdin, request)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "stdout": "", "history": []}
    if done.returncode == 99:
        return {"status": "too_long", "stdout": "", "history": []}
    if done.returncode != 0:
        return {"status": "error", "stdout": done.stdout[-STDOUT_TAIL:], "stderr": done.stderr[-STDERR_TAIL:], "history": []}
    if len(done.stdout) > request["max_output_chars"]:
        return {"status": "too_much_output", "stdout": "", "history": []}
    try:
        with open(trace_path, encoding="utf-8") as handle:
            history = json.load(handle)
    except (OSError, ValueError):
        return {"status": "error", "stdout": done.stdout, "stderr": "trace unavailable", "history": []}
    return {"status": "ok", "stdout": done.stdout, "history": history}


def analyze(source, request):
    tree, rejected = static_check(source)
    if rejected:
        return rejected

    deadline = time.monotonic() + request["deadline_sec"]
    folder = tempfile.mkdtemp(prefix="run-")
    try:
        write_text(os.path.join(folder, "tracer.py"), TRACER)
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
            results.append({**mutant, "status": run["status"], "stdout": run["stdout"][-MUTANT_STDOUT_TAIL:]})
        return {"status": "ok", "stdout": first["stdout"], "history": first["history"], "mutants": results}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def literal_args(text):
    """関数に渡す引数。リテラルの並びだけを認め、名前や呼び出しは通さない。"""
    if not isinstance(text, str) or len(text) > MAX_ARGS_CHARS:
        return None
    try:
        value = ast.literal_eval(text)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None
    return value if isinstance(value, (list, tuple)) else None


def call_function(folder, source, spec, request):
    path = os.path.join(folder, "program.py")
    spec_path = os.path.join(folder, "spec.json")
    out_path = os.path.join(folder, "probe.json")
    write_text(path, source)
    write_text(spec_path, json.dumps({"function": spec["function"], "args": spec["args"]}))
    if os.path.exists(out_path):
        os.remove(out_path)
    try:
        done = run_child(folder, "prober.py", [path, spec_path, out_path], "", request)
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    failed = {"status": "error", "detail": done.stderr[-STDERR_TAIL:]}
    try:
        with open(out_path, encoding="utf-8") as handle:
            result = json.load(handle)
    except (OSError, ValueError):
        return failed
    return result if done.returncode == 0 else failed


def probe(source, request):
    """主張を確かめる実行。1件ずつ別プロセスで動かし、時間制限をかける。"""
    # analyze と同じ検査。関数だけを呼ぶ確認でも、使えない名前を含むコードは動かさない
    tree, rejected = static_check(source)
    if rejected:
        return rejected
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}

    deadline = time.monotonic() + request["deadline_sec"]
    folder = tempfile.mkdtemp(prefix="probe-")
    try:
        write_text(os.path.join(folder, "prober.py"), PROBER)
        write_text(os.path.join(folder, "tracer.py"), TRACER)
        results = []
        for spec in request.get("probes", [])[: request.get("max_probes", DEFAULT_MAX_PROBES)]:
            kind = spec.get("kind") if isinstance(spec, dict) else None
            if time.monotonic() > deadline:
                results.append({"status": "skipped"})
            elif kind == "call" and literal_args(spec.get("args")) is None:
                results.append({"status": "bad_probe"})
            elif kind == "call" and spec.get("function") not in functions:
                results.append({"status": "no_function"})
            elif kind == "call":
                results.append(call_function(folder, source, spec, request))
            elif kind == "run" and isinstance(spec.get("stdin", ""), str):
                run = run_program(folder, source, spec.get("stdin", ""), request)
                results.append({"status": run["status"], "stdout": run["stdout"][-STDOUT_TAIL:]})
            else:
                results.append({"status": "bad_probe"})
        return {"status": "ok", "probes": results}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def main():
    with open("request.json", encoding="utf-8") as handle:
        request = json.load(handle)
    with open("student.py", encoding="utf-8") as handle:
        source = handle.read()
    result = probe(source, request) if request.get("mode") == "probe" else analyze(source, request)
    print(RESULT_PREFIX + json.dumps(result, ensure_ascii=False))


main()
