"""わざと質の低い小さなモデルで、高校生の提出物（コードと説明）を作る。合成データ専用。

python gen.py tasks.json out.jsonl [model] [samples]
"""
import json
import sys

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

tasks_path, out_path = sys.argv[1], sys.argv[2]
model_id = sys.argv[3] if len(sys.argv) > 3 else "Qwen/Qwen2.5-Coder-1.5B-Instruct"
samples = int(sys.argv[4]) if len(sys.argv) > 4 else 2

tok = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch.bfloat16, device_map="cuda")

CODE = """あなたはプログラミングを習い始めたばかりの高校1年生です。次の課題の Python のプログラムを書いてください。
- input() は使わず、データはプログラムの中に書く
- import は使わない
- 10〜20行くらい。コードだけを ```python で囲んで出す
課題: {task}"""

EXPLAIN = """あなたは高校1年生です。次のプログラムはあなたが書いたものです。先生に提出する説明を、日本語の短い文で3つか4つ書いてください。
- 1文に1つのことだけを書き、文の終わりは「。」にする
- 少なくとも1文は「〜のときは〜になる」「〜でも動く」のように、特別な入力のときの動きについて書く
- 説明だけを書く
課題: {task}
```python
{code}
```"""


def chat(text: str, temperature: float) -> str:
    prompt = tok.apply_chat_template([{"role": "user", "content": text}], add_generation_prompt=True, tokenize=False)
    ids = tok(prompt, return_tensors="pt")["input_ids"].to("cuda")
    out = model.generate(input_ids=ids, attention_mask=torch.ones_like(ids), max_new_tokens=512, do_sample=True, temperature=temperature, top_p=0.95)
    return tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True).strip()


def code_of(text: str) -> str:
    if "```" in text:
        text = text.split("```", 2)[1]
        text = text[len("python"):] if text.startswith("python") else text
    return text.strip() + "\n"


torch.manual_seed(0)
with open(tasks_path, encoding="utf-8") as handle, open(out_path, "w", encoding="utf-8") as out:
    for task in json.load(handle):
        for sample in range(samples):
            code = code_of(chat(CODE.format(task=task["task"]), 0.9))
            explanation = chat(EXPLAIN.format(task=task["task"], code=code), 0.9)
            row = {"task_id": task["id"], "sample": sample, "goal": task["goal"], "task": task["task"], "code": code, "explanation": explanation, "model": model_id}
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            print(task["id"], sample, flush=True)
