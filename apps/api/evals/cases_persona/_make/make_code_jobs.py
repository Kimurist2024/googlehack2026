"""コードを書かせる仕事の一覧（code_jobs.json）を作る。合成データ専用。

各課題で 8 つのペルソナを 4 つのモデルに 2 つずつ割り当てる。割り当ては課題ごとにずらし、
同じペルソナがいつも同じモデルにならないようにする。
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "cases_lowq2" / "_make"))
import tasks2  # noqa: E402
from personas import PERSONAS  # noqa: E402

MODELS = [
    "microsoft/Phi-3.5-mini-instruct",
    "ibm-granite/granite-3.1-2b-instruct",
    "Qwen/Qwen2.5-Coder-3B-Instruct",
    "allenai/OLMo-2-0425-1B-Instruct",
]

PROMPT = """You are a high school student who started learning Python two months ago. Write a short Python program for the assignment below, the way a beginner would.
Your habits: {habit}
- Do not use import.
- Keep it short and simple.
- Output only the code inside a ```python block.
Assignment: {task}"""


def jobs() -> list[dict]:
    out = []
    for t, task in enumerate(tasks2.TASKS):
        for p, persona in enumerate(PERSONAS):
            model = MODELS[(p + t) % len(MODELS)]
            out.append({"task_id": task["id"], "persona": persona["id"], "model": model,
                        "prompt": PROMPT.format(habit=persona["code"], task=task["en"])})
    return out


if __name__ == "__main__":
    (HERE / "code_jobs.json").write_text(json.dumps(jobs(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
