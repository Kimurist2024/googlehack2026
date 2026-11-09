"""Colab の GPU で、小さなモデルに文章を書かせる。合成データ専用。

python gen_colab.py JOBS.json OUT.jsonl MODEL_ID SAMPLES [MAX_NEW_TOKENS] [TEMPERATURE]
JOBS の中で model が MODEL_ID のものだけを、SAMPLES 件ずつ書かせて OUT に足す。
すでに OUT にある仕事（key が同じもの）は飛ばすので、途中で切れても続きから動かせる。
"""
import json
import os
import sys

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

jobs_path, out_path, model_id, samples = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
max_new = int(sys.argv[5]) if len(sys.argv) > 5 else 400
temperature = float(sys.argv[6]) if len(sys.argv) > 6 else 1.0
jobs = [j for j in json.load(open(jobs_path, encoding="utf-8")) if j["model"] == model_id]


def key(job):
    return job.get("key") or f"{job['task_id']}|{job['persona']}"


done = set()
if os.path.exists(out_path):
    done = {json.loads(line)["key"] for line in open(out_path, encoding="utf-8")}

tok = AutoTokenizer.from_pretrained(model_id)
tok.padding_side = "left"
if tok.pad_token is None:
    tok.pad_token = tok.eos_token
model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch.float16, device_map="cuda")
torch.manual_seed(0)

with open(out_path, "a", encoding="utf-8") as out:
    for job in jobs:
        if key(job) in done:
            continue
        text = tok.apply_chat_template([{"role": "user", "content": job["prompt"]}], add_generation_prompt=True, tokenize=False)
        enc = tok(text, return_tensors="pt", add_special_tokens=False).to("cuda")
        enc.pop("token_type_ids", None)  # llm-jp などの tokenizer が返すが、generate は受け取らない
        with torch.no_grad():
            gen = model.generate(**enc, max_new_tokens=max_new, do_sample=True, temperature=temperature, top_p=0.95,
                                 num_return_sequences=samples, pad_token_id=tok.pad_token_id)
        for i, seq in enumerate(gen):
            reply = tok.decode(seq[enc["input_ids"].shape[1]:], skip_special_tokens=True)
            row = {k: v for k, v in job.items() if k != "prompt"}
            out.write(json.dumps(row | {"key": key(job), "sample": i, "reply": reply}, ensure_ascii=False) + "\n")
        out.flush()
        print(model_id, key(job), flush=True)
