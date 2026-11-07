"""Colab の GPU で、小さなモデルに初心者のコードを書かせる。合成データ専用。

prompts.json（課題 id と英語の課題文）を読み、モデルごとに samples 件ずつ書かせて out.jsonl に足す。
説明文は書かせない（モデルの日本語のクセを入れないため）。
"""
import json
import sys

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

model_id = sys.argv[1]
samples = int(sys.argv[2]) if len(sys.argv) > 2 else 6
tasks = json.load(open("prompts.json", encoding="utf-8"))

PROMPT = """You are a high school student who started learning Python two months ago. Write a short Python program for the assignment below, the way a beginner would.
- Do not use import.
- Keep it short and simple.
- Output only the code inside a ```python block.
Assignment: {task}"""

tok = AutoTokenizer.from_pretrained(model_id)
tok.padding_side = "left"
if tok.pad_token is None:
    tok.pad_token = tok.eos_token
model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch.float16, device_map="cuda")
torch.manual_seed(0)

with open("out.jsonl", "a", encoding="utf-8") as out:
    for task in tasks:
        text = tok.apply_chat_template([{"role": "user", "content": PROMPT.format(task=task["en"])}], add_generation_prompt=True, tokenize=False)
        enc = tok(text, return_tensors="pt").to("cuda")
        with torch.no_grad():
            gen = model.generate(**enc, max_new_tokens=400, do_sample=True, temperature=1.0, top_p=0.95, num_return_sequences=samples, pad_token_id=tok.pad_token_id)
        for i, seq in enumerate(gen):
            reply = tok.decode(seq[enc["input_ids"].shape[1]:], skip_special_tokens=True)
            out.write(json.dumps({"task_id": task["id"], "model": model_id, "sample": i, "reply": reply}, ensure_ascii=False) + "\n")
        out.flush()
        print(model_id, task["id"], flush=True)
