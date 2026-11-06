"""改善する対象（どの段階の指示文か）と、その指示文で動く流れの組み立て方。

チームの他の段階（主張の分解など）も、Target を1つ足せば同じループで改善できる。
"""
from dataclasses import dataclass, field
from typing import Callable

from evalh.pipeline import Pipeline
from qgen.prompt_store import load_active


@dataclass
class Target:
    name: str
    initial: str  # 今使っている版（ACTIVE）の指示文
    build: Callable[[str], Pipeline]  # 指示文 → 評価できる流れ
    notes: Callable[[], list[dict]] = field(default=lambda: [])  # 直前に組み立てた流れの出力の記録
    api_errors: Callable[[], int] = field(default=lambda: 0)  # 直前に組み立てた流れで、AI の呼び出しが失敗した回数


def probe_planner(client, model: str, sandbox) -> Target:
    """動きの主張の確かめ方を Gemini に決めさせる段階。根拠探しと主張の分解は偽物のままにして、この段階だけを測る。"""
    from evalh.behavior import ProbingFinder
    from evalh.fakes import LexiconFinder, SentenceDecomposer, TemplateWriter
    from evalh.pipeline import StagedPipeline
    from qgen.probes import PROBE_TARGET, GeminiProbePlanner

    last: dict = {}

    def build(prompt: str) -> Pipeline:
        planner = GeminiProbePlanner(client, model, prompt=prompt)
        finder = ProbingFinder(LexiconFinder(), planner, sandbox)
        last["finder"], last["planner"] = finder, planner
        return StagedPipeline(PROBE_TARGET, SentenceDecomposer(), finder, TemplateWriter())

    def notes() -> list[dict]:
        return list(last["finder"].log) if "finder" in last else []

    def api_errors() -> int:
        return last["planner"].api_errors if "planner" in last else 0

    return Target(PROBE_TARGET, load_active(PROBE_TARGET), build, notes, api_errors)
