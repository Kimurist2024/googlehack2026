"""小さなモデルが書いたコードから、評価用の模擬提出物（cases_lowq2）を作る。合成データ専用。

1. コードからモデルのクセを機械的に取る（コメント・docstring・型ヒント・__main__ の囲み・input の案内文）。
   日本語以外の文字（中国語など）を含む文字列があるコードは使わない。誤り（バグ）はそのまま残す。
2. 生徒は「課題どおりに動くはず」と思って説明を書く。主張の値は模範解答（tasks2.ref）から取り、
   一部はわざと計算違いにする。文は tasks2 の型と終わり方の言い回しから選ぶ（モデルには書かせない）。
3. 主張の正解は、生徒のコードを実行ハーネスで動かして決める（主張どおり → correct、食い違う → gap）。
   どちらとも言えない主張（時間切れ、定義だけでは呼べない関数など）は使わない。

cd apps/api && APP_ENV=local ALLOW_LOCAL_SANDBOX=1 PYTHONPATH=. .venv/bin/python evals/cases_lowq2/_make/build.py evals/cases_lowq2/_make/generated.jsonl evals/cases_lowq2
"""
import ast
import json
import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tasks2  # noqa: E402
from qgen import probes as P  # noqa: E402
from qgen.sandbox import LocalDevSandbox, SandboxError  # noqa: E402

rng = random.Random(20261106)
ENDINGS = {
    "{N}": ["になる", "になります", "になるはず", "になった", "になると思う", "になる（たぶん）"],
    "{K}": ["を返す", "が返ってくる", "が返る", "を返します", "が返ってきた", "を返すはず"],
    "{H}": ["と表示される", "が表示される", "と出る", "と出ました", "が出るはず", "と表示されます"],
}
WRONG_RATE = 0.15  # 生徒の計算違いの割合
MAX_PER_TASK = 3
ALLOWED_TEXT = re.compile(r"^[\x20-\x7e぀-ヿ一-鿿々ー、。！？「」（）：・\n\t]*$")
SIMPLIFIED = set("这们个为输现实时对么还没获计结检遍历让将给并处断该吗应值组")


# ---- 1. クセを取る ----
class Clean(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        node.returns = None
        for arg in node.args.args + node.args.kwonlyargs:
            arg.annotation = None
        node.body = strip_doc(node.body) or [ast.Pass()]
        return node

    def visit_AnnAssign(self, node):
        if node.value is None:
            return None
        return ast.copy_location(ast.Assign(targets=[node.target], value=node.value), node)

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "input":
            node.args, node.keywords = [], []
        return node


def strip_doc(body):
    return [s for s in body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))]


def quiet_print(node):
    """関数の課題で、試しに表示する行の英語の見出し（"The max is:" など）を外す。値はそのまま表示する。"""
    if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "print"):
        return node
    args = []
    for arg in node.value.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            continue
        if isinstance(arg, ast.JoinedStr):
            args += [part.value for part in arg.values if isinstance(part, ast.FormattedValue)]
            continue
        args.append(arg)
    if not args:
        return None
    node.value.args, node.value.keywords = args, []
    return node


def is_main_guard(node):
    return isinstance(node, ast.If) and "__name__" in ast.unparse(node.test)


def code_of(reply: str) -> str | None:
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", reply, re.S)
    return m.group(1) if m else None


def clean(source: str, task: dict) -> tuple[str | None, str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, "syntax"
    body = []
    for node in tree.body:
        body.extend(node.body if is_main_guard(node) else [node])
    tree.body = strip_doc(body)
    tree = ast.fix_missing_locations(Clean().visit(tree))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef, ast.AsyncFunctionDef)):
            return None, "import/class"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            kanji = {ch for ch in node.value if "\u4e00" <= ch <= "\u9fff"}
            # 漢字は課題文に出てくるもの（発射・偶数など）だけ。ほかは中国語のクセとみなす
            if not ALLOWED_TEXT.match(node.value) or SIMPLIFIED & set(node.value) or kanji - set(task["en"]):
                return None, "foreign_text"
    if task["kind"] == "call":
        tree.body = [n for n in (quiet_print(n) for n in tree.body) if n is not None]
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    if task["kind"] == "call":
        ref = next(n for n in ast.parse(task["ref"]).body if isinstance(n, ast.FunctionDef))
        f = funcs.get(task["func"])
        if f is None or len(f.args.args) != len(ref.args.args) or f.args.vararg or f.args.defaults:
            return None, "signature"
    else:
        if not any(isinstance(n, (ast.For, ast.While)) for n in ast.walk(tree)) and task["kind"] == "run":
            return None, "no_loop"
    code = ast.unparse(tree) + "\n"
    if not 2 <= code.count("\n") <= 40:
        return None, "length"
    if task["kind"] == "stdin" and "input(" not in code:
        return None, "no_input"
    return code, "ok"


# ---- 2. 生徒が思っている値（模範解答） ----
def ref_call(task, args):
    ns = {}
    exec(task["ref"], ns)
    try:
        return ("value", ns[task["func"]](*args))
    except Exception:
        return ("raised", None)


def ref_stdout(task, stdin):
    done = subprocess.run([sys.executable, "-I", "-c", task["ref"]], input=stdin, capture_output=True, text=True, timeout=5)
    return [line.strip() for line in done.stdout.splitlines()]


def wrong(v):
    """もっともらしい計算違い。作れないときは None。"""
    if isinstance(v, bool):
        return not v
    if isinstance(v, int):
        return v + rng.choice([-1, 1]) if v else 1
    if isinstance(v, float):
        return v + 5.0
    if isinstance(v, str) and v in ("A", "B", "C"):
        return {"A": "B", "B": rng.choice("AC"), "C": "B"}[v]
    if isinstance(v, str) and v in ("Fizz", "Buzz", "FizzBuzz"):
        return {"Fizz": "Buzz", "Buzz": "Fizz", "FizzBuzz": "Fizz"}[v]
    if isinstance(v, str) and v in ("偶数", "奇数"):
        return {"偶数": "奇数", "奇数": "偶数"}[v]
    if isinstance(v, str) and v in ("子ども", "10代", "大人"):
        return {"子ども": "10代", "10代": rng.choice(["子ども", "大人"]), "大人": "10代"}[v]
    if isinstance(v, list) and len(v) >= 2 and v != v[::-1]:
        return v[::-1]
    return None


def belief(task, spec):
    """(主張の文, 確かめる Probe) の候補。生徒が思っている値で作る。"""
    kind = spec[0]
    if kind == "call":
        status, v = ref_call(task, spec[1])
        if status != "value":
            return None
        if rng.random() < WRONG_RATE and wrong(v) is not None:
            v = wrong(v)
        probe = P.Probe("call", "returns", repr(v), function=task["func"], args=repr(list(spec[1])))
        return spec[2](v, *spec[1]), probe
    if kind == "raises":
        r = ref_call(task, spec[1])[0] == "raised"
        if rng.random() < WRONG_RATE:
            r = not r
        probe = P.Probe("call", "raises", "true" if r else "false", function=task["func"], args=repr(list(spec[1])))
        return spec[2](r, *spec[1]), probe
    if kind == "stdin":
        lines = ref_stdout(task, spec[1])
        v = lines[-1]
        if rng.random() < WRONG_RATE and wrong(v) is not None:
            v = wrong(v)
        elif rng.random() < WRONG_RATE and v.lstrip("-").isdigit():
            v = str(int(v) + 1)
        return spec[2](v, spec[1]), P.Probe("run", "stdout_line", v, stdin=spec[1])
    if kind == "line":
        present = spec[2] in ref_stdout(task, spec[1])
        if rng.random() < WRONG_RATE:
            present = not present
        return spec[3](present, spec[2]), P.Probe("run", "stdout_line" if present else "no_stdout_line", spec[2], stdin=spec[1])
    raise ValueError(kind)


def render(template: str) -> str:
    for key, options in ENDINGS.items():
        template = template.replace(key, rng.choice(options))
    return template


# ---- 3. 実行して正解を決める ----
sandbox = LocalDevSandbox()


def verdict(code: str, probe: P.Probe) -> str:
    try:
        result = sandbox.probe(code, [probe.request()])
    except SandboxError:
        return P.UNKNOWN
    outcomes = result.get("probes", []) if result.get("status") == "ok" else []
    return P.verdict(probe, outcomes[0]) if outcomes else P.UNKNOWN


def matches_ref(code, task, spec) -> bool | None:
    """生徒のコードが模範解答と同じに動くか（バグの有無の目印）。"""
    kind = spec[0]
    if kind in ("call", "raises"):
        status, v = ref_call(task, spec[1])
        probe = P.Probe("call", "raises", "true", function=task["func"], args=repr(list(spec[1]))) if status == "raised" else P.Probe("call", "returns", repr(v), function=task["func"], args=repr(list(spec[1])))
    elif kind == "stdin":
        probe = P.Probe("run", "stdout_line", ref_stdout(task, spec[1])[-1], stdin=spec[1])
    else:
        present = spec[2] in ref_stdout(task, spec[1])
        probe = P.Probe("run", "stdout_line" if present else "no_stdout_line", spec[2], stdin=spec[1])
    out = verdict(code, probe)
    return None if out == P.UNKNOWN else out == P.HOLDS


def structure_claims(code: str, task: dict) -> list[tuple[str, list]]:
    tree = ast.parse(code)
    out = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == task.get("func"):
            out.append((rng.choice([f"{node.name}という関数を作った", f"関数{node.name}を書きました", f"{node.name}って名前の関数にした"]), [[node.lineno, node.end_lineno]]))
    loops = [n for n in ast.walk(tree) if isinstance(n, (ast.For, ast.While))]
    if loops:
        n = loops[0]
        word = "for" if isinstance(n, ast.For) else "while"
        out.append((rng.choice([f"{word}でくり返している", f"{word}文を使って1つずつ見ている", f"くり返しには{word}を使った"]), [[n.lineno, n.end_lineno]]))
    ifs = [n for n in ast.walk(tree) if isinstance(n, ast.If)]
    if ifs:
        out.append((rng.choice(["ifで場合分けしている", "if文で条件を分けた"]), [[ifs[0].lineno, ifs[0].lineno]]))
    rng.shuffle(out)
    return out[: rng.choice([1, 1, 2])]


def behavior_evidence(code: str, task: dict) -> list:
    tree = ast.parse(code)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == task.get("func"):
            return [[node.lineno, node.end_lineno]]
    return [[1, code.count("\n")]]


def main(out_path: str, root: str) -> None:
    rows = [json.loads(line) for line in open(out_path, encoding="utf-8")]
    tasks = {t["id"]: t for t in tasks2.TASKS}
    stats: dict[str, int] = {}
    pool: dict[str, list] = {t: [] for t in tasks}
    seen = set()
    for row in rows:
        task = tasks[row["task_id"]]
        source = code_of(row["reply"])
        code, why = clean(source, task) if source else (None, "no_code")
        if code and code in seen:
            why, code = "duplicate", None
        stats[why] = stats.get(why, 0) + 1
        if not code:
            continue
        seen.add(code)
        signature = tuple(matches_ref(code, task, spec) for spec in task["claims"])
        if all(s is None for s in signature):
            stats["all_unknown"] = stats.get("all_unknown", 0) + 1
            continue
        pool[task["id"]].append((row, code, signature))
    print("filter:", stats)

    total = {"correct": 0, "gap": 0, "structure": 0}
    made = 0
    for task_id, items in pool.items():
        task = tasks[task_id]
        # バグの出方（signature）が違うものを、モデルを散らして選ぶ
        rng.shuffle(items)
        items.sort(key=lambda it: -sum(s is False for s in it[2]))
        chosen, sigs, models = [], set(), {}
        for it in items:
            if it[2] in sigs or models.get(it[0]["model"], 0) >= 2:
                continue
            chosen.append(it)
            sigs.add(it[2])
            models[it[0]["model"]] = models.get(it[0]["model"], 0) + 1
            if len(chosen) == MAX_PER_TASK:
                break
        for n, (row, code, signature) in enumerate(chosen, 1):
            specs = [s for s, ok in zip(task["claims"], signature) if ok is not None]
            rng.shuffle(specs)
            behaviors = []
            for spec in specs[: rng.choice([3, 3, 4])]:
                texts, probe = belief(task, spec)
                outcome = verdict(code, probe)
                if outcome == P.UNKNOWN:
                    continue
                label = "correct" if outcome == P.HOLDS else "gap"
                behaviors.append((render(rng.choice(texts)), label, probe))
            if not behaviors:
                continue
            claims = [(t, "correct", "structure", e, None) for t, e in structure_claims(code, task)]
            claims += [(t, label, "behavior", behavior_evidence(code, task) if label == "correct" else [], probe) for t, label, probe in behaviors]
            case_id = f"{task_id}_{n}"
            split = "heldout" if task_id in tasks2.HELDOUT else "dev"
            folder = Path(root) / case_id
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "program.py").write_text(code, encoding="utf-8")
            (folder / "explanation.txt").write_text("。".join(c[0] for c in claims) + "。\n", encoding="utf-8")
            gold = {
                "split": split,
                "goal": task["goal"],
                "source": f"{row['model']} が書いた {task_id} のコード（クセを取ったもの）と、型から作った説明（合成データ）",
                "claims": [
                    {"id": f"g{i}", "text": t, "label": l, "kind": k, "evidence": e} | ({"check": {k2: v2 for k2, v2 in vars(p).items()}} if p else {})
                    for i, (t, l, k, e, p) in enumerate(claims, 1)
                ],
            }
            (folder / "gold.json").write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            made += 1
            for c in claims:
                total["structure" if c[2] == "structure" else c[1]] += 1
    print("cases:", made, total)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
