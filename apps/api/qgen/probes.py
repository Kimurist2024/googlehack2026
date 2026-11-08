"""生徒の説明のうち「動き」についての主張を、コードを動かして確かめる。

どう確かめるか（probe）は規則か Gemini が決め、確かめた結果が主張どおりかはここで機械的に判定する。
AIは「何を試すか」だけを決め、合否には関わらない。

今は評価ハーネス（evalh/）と RSI で検証している段階で、授業の流れ（app/）からはまだ呼んでいない。
"""
import ast
import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass
from typing import Protocol

from .ai import DATA_NOTICE, as_data, gemini_guard, strip_comments
from .guard import Guard, NoGuard
from .prompt_store import load_active

logger = logging.getLogger(__name__)
MAX_PROBES = 3
MAX_ARGS_CHARS = 200
EXPECT_KINDS = ("raises", "returns", "stdout_line", "no_stdout_line")
HOLDS, FAILS, UNKNOWN = "holds", "fails", "unknown"
# 混んでいるときの一時的な失敗（429 など）は、待ってからやり直す。続けて失敗したら規則に戻す
RETRY_CODES = {429, 500, 503}
RETRY_WAITS = (2.0, 5.0, 12.0)
# 定義を取り出して呼ぶので、最上位の変数を使う関数ではこの例外が出る。生徒の誤りとは決めない
SETUP_ERRORS = {"NameError"}


@dataclass(frozen=True)
class Probe:
    kind: str  # call: 関数を1つ呼ぶ / run: プログラム全体を動かす
    expect_kind: str
    expect_value: str  # raises は "true"/"false"、returns はリテラル、stdout_line は1行の文字列
    function: str = ""
    args: str = "[]"  # 引数の並びをリテラルで書いたもの
    stdin: str = ""

    def request(self) -> dict:
        return {key: value for key, value in asdict(self).items() if key in ("kind", "function", "args", "stdin")}


def _literal(text: str) -> object:
    return ast.literal_eval(text)


def validate(raw: object) -> Probe | None:
    """形が少しでもおかしい probe は捨てる。Gemini の出力もここを通す。"""
    if not isinstance(raw, dict):
        return None
    try:
        probe = Probe(**{key: str(raw[key]) for key in raw if key in Probe.__dataclass_fields__})
    except TypeError:
        return None
    if probe.kind not in ("call", "run") or probe.expect_kind not in EXPECT_KINDS:
        return None
    if probe.kind == "call":
        if not probe.function.isidentifier() or probe.function.startswith("_") or len(probe.args) > MAX_ARGS_CHARS:
            return None
        try:
            if not isinstance(_literal(probe.args), (list, tuple)):
                return None
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            return None
        if probe.expect_kind not in ("raises", "returns"):
            return None
    elif probe.expect_kind not in ("stdout_line", "no_stdout_line") or len(probe.stdin) > MAX_ARGS_CHARS:
        return None
    if probe.expect_kind == "raises" and probe.expect_value not in ("true", "false"):
        return None
    if probe.expect_kind == "returns":
        try:
            _literal(probe.expect_value)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            return None
    return probe


def verdict(probe: Probe, result: dict) -> str:
    """1件の実行結果が、主張どおりか（holds）、食い違うか（fails）、分からないか（unknown）。"""
    if not isinstance(result, dict) or result.get("status") != "ok":
        return UNKNOWN
    if probe.kind == "call":
        raised = result.get("raised")
        if raised in SETUP_ERRORS:
            return UNKNOWN
        if probe.expect_kind == "raises":
            return HOLDS if bool(raised) == (probe.expect_value == "true") else FAILS
        if raised:
            return FAILS
        return HOLDS if result.get("returned") == repr(_literal(probe.expect_value)) else FAILS
    lines = [line.strip() for line in str(result.get("stdout", "")).splitlines()]
    present = probe.expect_value.strip() in lines
    return HOLDS if present == (probe.expect_kind == "stdout_line") else FAILS


def combine(verdicts: list[str]) -> str:
    """1つでも食い違えば fails。すべて主張どおりなら holds。"""
    if FAILS in verdicts:
        return FAILS
    if verdicts and all(item == HOLDS for item in verdicts):
        return HOLDS
    return UNKNOWN


def functions_of(code: str) -> dict[str, int]:
    """最上位の関数の名前と引数の数。コードは実行しない。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}
    return {node.name: len(node.args.args) for node in tree.body if isinstance(node, ast.FunctionDef)}


def with_retry(call):
    """一時的な失敗（RETRY_CODES）だけ、RETRY_WAITS の秒数だけ待ってやり直す。それ以外の失敗はそのまま投げる。"""
    for wait in (*RETRY_WAITS, None):
        try:
            return call()
        except Exception as error:
            if wait is None or getattr(error, "code", None) not in RETRY_CODES:
                raise
            time.sleep(wait)


class ProbePlanner(Protocol):
    def plan(self, claim: str, code: str) -> list[Probe]: ...


class PatternProbePlanner:
    """AIを使わない既定の決め方。よくある言い回しだけを拾う。"""

    def plan(self, claim: str, code: str) -> list[Probe]:
        single = [name for name, count in functions_of(code).items() if count == 1]
        found: list[Probe] = []
        if re.search(r"空(?:の(?:リスト|配列))?でも", claim):
            found += [Probe("call", "raises", "false", function=name, args="[[]]") for name in single]
        exact = re.search(r"(-?\d+)\D{0,3}ちょうど(?:は|なら|のとき)、?(\w+?)(?:に|を返|と)", claim)
        if exact and len(single) == 1:
            value = exact.group(2)
            expected = value if value.lstrip("-").isdigit() else repr(value)
            found.append(Probe("call", "returns", expected, function=single[0], args=f"[{exact.group(1)}]"))
        shown = re.search(r"(-?\d+)も(?:表示|出力)", claim)
        if shown:
            found.append(Probe("run", "stdout_line", shown.group(1)))
        hidden = re.search(r"(-?\d+)は(?:表示|出力)しない", claim)
        if hidden:
            found.append(Probe("run", "no_stdout_line", hidden.group(1)))
        return found[:MAX_PROBES]


PROBE_SCHEMA = {
    "type": "object",
    "properties": {
        "probes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["call", "run"]},
                    "function": {"type": "string"},
                    "args": {"type": "string"},
                    "stdin": {"type": "string"},
                    "expect_kind": {"type": "string", "enum": list(EXPECT_KINDS)},
                    "expect_value": {"type": "string"},
                },
                "required": ["kind", "expect_kind", "expect_value"],
            },
        }
    },
    "required": ["probes"],
}

PROBE_TARGET = "probe_planner"  # 指示文は qgen/prompts/probe_planner/ に版つきで置く


def student_data(claim: str, code: str) -> str:
    """指示文の {data} に入れる文。注意書きと <data> の囲みはここで付けるので、指示文を書き直しても外れない。"""
    return f"{DATA_NOTICE}\n" + as_data(f"主張: {claim}\nコード:\n{strip_comments(code)}")


class GeminiProbePlanner:
    """Gemini に「何を試すか」だけを決めさせる。検査を通らなければ規則の決め方に戻す。

    生徒の主張とコードは Model Armor（guard）で検査してから渡す。返答は人に見せず、
    形と関数名を確かめてから実行に使うだけなので、返答の検査はしない。
    """

    def __init__(
        self, client, model: str, fallback: ProbePlanner | None = None, prompt: str | None = None, guard: Guard | None = None
    ) -> None:
        self._client = client
        self._model = model
        self._fallback = fallback or PatternProbePlanner()
        self._guard = guard or NoGuard()
        # 呼び出し自体の失敗（上限、ネットワークなど）で規則に戻した回数。返答の形が悪かったときは数えない。
        # 評価では、これが1回でもあると指示文の良し悪しが測れないので、その回を使わない
        self.api_errors = 0
        self._lock = threading.Lock()  # 評価では提出物ごとに並行して呼ぶ
        self.prompt = prompt if prompt is not None else load_active(PROBE_TARGET)  # 自動改善では候補を渡す

    def _generate(self, prompt: str):
        return with_retry(lambda: self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config={"response_mime_type": "application/json", "response_json_schema": PROBE_SCHEMA},
        ))

    def plan(self, claim: str, code: str) -> list[Probe]:
        data = student_data(claim, code)
        if not self._guard.screen_prompt(data):
            return self._fallback.plan(claim, code)
        prompt = self.prompt.format(limit=MAX_PROBES, data=data)
        try:
            response = self._generate(prompt)
        except Exception:
            with self._lock:
                self.api_errors += 1
            logger.exception("Gemini を呼べなかったので、規則の決め方に戻します")
            return self._fallback.plan(claim, code)
        try:
            payload = json.loads(response.text)
            raw = payload.get("probes") if isinstance(payload, dict) else None
            if not isinstance(raw, list):
                raise ValueError("probes がありません")
        except Exception:
            logger.exception("Gemini の確かめ方の作成に失敗しました")
            return self._fallback.plan(claim, code)
        known = functions_of(code)
        probes = [p for p in (validate(item) for item in raw[:MAX_PROBES]) if p and (p.kind == "run" or p.function in known)]
        if len(probes) != len(raw[:MAX_PROBES]):
            logger.warning("Gemini の確かめ方の一部が検査を通らなかったので捨てました")
        return probes


def default_probe_planner(client=None) -> ProbePlanner:
    """qgen.ai.default_ai と同じ決まりで選ぶ。本番で Model Armor の設定がなければ Gemini を使わない。"""
    import os

    if os.environ.get("AI_BACKEND", "template") != "gemini":
        return PatternProbePlanner()
    guard = gemini_guard()
    if guard is None:
        return PatternProbePlanner()
    if client is None:
        from google import genai

        client = genai.Client(enterprise=True, project=os.environ["GOOGLE_CLOUD_PROJECT"], location=os.environ.get("GEMINI_LOCATION", "global"))
    return GeminiProbePlanner(client, os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"), guard=guard)
