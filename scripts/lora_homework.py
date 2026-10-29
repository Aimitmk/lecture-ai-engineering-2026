"""第2回 宿題: notebooks/lora_format_tuning.ipynb のセクション 1〜7 を、1 回の実行（ラン）を 1 プロセスで行うスクリプトにしたもの。

使い方（Colab では notebooks/lec02_homework.ipynb から呼ぶ）:
    python -m scripts.lora_homework --run baseline --out <結果の保存先>
    python -m scripts.lora_homework --run glossary --out <結果の保存先>
    python -m scripts.lora_homework --run baseline --out /tmp/smoke --smoke   # 動作確認（2 ステップ・数問だけ）
    uv run python -m scripts.lora_homework --summary            # lectures/02/results/*/result.json を Markdown の表にする（torch 不要）
    uv run python -m scripts.lora_homework --detail baseline    # 1 つのランの、質問ごとの出力を表にする（torch 不要）

ラン（RUNS）:
    baseline  ノートブックの CONFIG のまま（演習・基礎の基準）
    epochs5   num_train_epochs 20→5（基礎）
    lr5e-5    lr 2e-4→5e-5（基礎）
    r4        lora_r 16→4（基礎）
    crypto    FAQ を架空の暗号資産取引所に置き換える（実装）
    glossary  用語集から作った SFT データで学習し、用語集の検索と比べる（発展）

ノートブックと同じにしているもの: CONFIG、SYSTEM、build_messages、generate、check_format、check_content、evaluate、
to_chat、LoraConfig、SFTConfig、知識質問、result.json のキー。
ノートブックに足したもの（学習には影響しない）: result.json の train（学習時間・loss の履歴・valid loss など）と env（GPU・版・commit）。
1 つのランを 1 つのプロセスで行うので、「設定を変えたらセッションを再起動して上から実行する」のと同じになる。
torch などはランを実行する関数の中でだけ import するので、--summary と --detail は torch なしで動く。
"""

import argparse
import difflib
import json
import platform
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from scripts import lora_data

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "lectures" / "02" / "results"
GLOSSARY_SFT = ROOT / "lectures" / "02" / "data" / "glossary_sft.jsonl"

# ノートブックのセクション 1 の CONFIG（work_dir と drive_dir は除く）
BASE_CONFIG = {
    "base_model": "Qwen/Qwen3.5-0.8B",
    "revision": "2fc06364715b967f1860aea9cf38778875588b17",
    "seed": 42,
    "num_train_epochs": 20,
    "warmup_steps": 6,
    "lr": 2e-4,
    "lora_r": 16,
    "lora_alpha": 32,
    "max_seq_len": 512,
    "max_new_tokens": 96,
    "gen": {"do_sample": False},
}

RUNS = {
    "baseline": {"data": "course", "config": {}, "note": "ノートブックの CONFIG のまま"},
    "epochs5": {"data": "course", "config": {"num_train_epochs": 5}, "note": "num_train_epochs 20→5"},
    "lr5e-5": {"data": "course", "config": {"lr": 5e-5}, "note": "lr 2e-4→5e-5"},
    "r4": {"data": "course", "config": {"lora_r": 4}, "note": "lora_r 16→4（lora_alpha は 32 のまま）"},
    "crypto": {"data": "crypto", "config": {}, "note": "FAQ を架空の暗号資産取引所に置き換え"},
    # 定義は最長 212 字あるので、生成の上限を 256 トークンに広げる
    "glossary": {"data": "glossary", "config": {"num_train_epochs": 10, "max_new_tokens": 256}, "note": "用語集の SFT データ（116 件）で 10 エポック"},
}
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


# ---- ノートブックのセクション 3〜7 と同じ処理 ----

def build_messages(example, system):
    user = f"FAQ:\n{example['faq']}\n\n質問: {example['question']}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def to_chat(example, system):
    # 学習データは「入力（system + user）」と「望ましい出力（assistant）」の対。評価と同じ build_messages を使う
    return {"messages": build_messages(example, system) + [{"role": "assistant", "content": example["target"]}]}


def check_format(text: str):
    '''JSON として読め、必須キーと型が合うか。失敗理由も返す'''
    try:
        obj = json.loads(text)
    except Exception as e:
        return False, f"json_error: {type(e).__name__}", None
    if not isinstance(obj, dict): return False, "not_object", None
    if set(obj) - {"answer", "needs_review"}: return False, "extra_keys", obj
    if "answer" not in obj or "needs_review" not in obj: return False, "missing_key", obj
    if not isinstance(obj["answer"], str) or not isinstance(obj["needs_review"], bool): return False, "wrong_type", obj
    return True, "", obj


def loose_parse(raw: str, ok_fmt: bool, obj):
    # 形式が壊れていても JSON らしい部分が読めるなら、内容だけは別に採点する（ノートブックの evaluate と同じ）
    loose = obj
    if not ok_fmt:
        m = re.search(r"\{.*\}", raw, re.S)
        try: loose = json.loads(m.group(0)) if m else None
        except Exception: loose = None
    return loose if isinstance(loose, dict) else None


def check_content(obj, gold_entry):
    '''内容の合否: needs_review が正解と一致し、必須語句を answer に含む'''
    if obj is None: return False
    if obj.get("needs_review") != gold_entry["needs_review"]: return False
    return all(w in obj.get("answer", "") for w in gold_entry["must_include"])


def classify(raw):
    ok, _, obj = check_format(raw)
    if not ok or obj is None: return "format_error"
    return "needs_review" if obj["needs_review"] else "asserted"


def load_model(config, device=None):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = device or ("cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu"))
    tok = AutoTokenizer.from_pretrained(config["base_model"], revision=config["revision"])
    if tok.pad_token is None: tok.pad_token = tok.eos_token
    # 量子化なし。重みは 32bit のまま保持する
    model = AutoModelForCausalLM.from_pretrained(config["base_model"], revision=config["revision"], dtype=torch.float32).to(device)
    model.config.use_cache = True
    print("loaded:", config["base_model"], "| device:", device, "| 重みのメモリ(GB):", round(model.get_memory_footprint() / 1e9, 2), flush=True)
    return tok, model, device


def generate(model, tok, messages, config):
    import torch

    # enable_thinking=False: 思考ブロックを空にして回答だけを生成させる
    prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    inputs = tok(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=config["max_new_tokens"], pad_token_id=tok.pad_token_id, **config["gen"])
    return tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def evaluate(gen, test, gold, label, out: Path):
    '''test を生成して採点し、要約と質問ごとの結果を返す。原文は eval_<label>.json に保存する'''
    rows = []
    t0 = time.time()
    for ex in test:
        raw = gen(ex)
        ok_fmt, reason, obj = check_format(raw)
        ok_content = check_content(loose_parse(raw, ok_fmt, obj), gold[ex["question"]])
        rows.append({"question": ex["question"], "raw": raw, "format_ok": ok_fmt, "format_reason": reason,
                     "content_ok": ok_content, "both_ok": ok_fmt and ok_content, "gold_needs_review": gold[ex["question"]]["needs_review"]})
    n = len(rows)
    summary = {"label": label, "n": n,
               "format_rate": sum(r["format_ok"] for r in rows)/n,
               "content_rate": sum(r["content_ok"] for r in rows)/n,
               "both_rate": sum(r["both_ok"] for r in rows)/n,
               "seconds": round(time.time()-t0, 1)}
    (out / f"eval_{label}.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary, rows


def train_lora(model, tok, train_records, valid_records, config, work: Path, smoke: bool, device: str):
    from datasets import Dataset
    from peft import LoraConfig
    from trl import SFTConfig, SFTTrainer

    train_ds = Dataset.from_list(train_records)
    valid_ds = Dataset.from_list(valid_records) if valid_records else None
    model.config.use_cache = False
    # Qwen3.5 は 24 層のうち 18 層が線形注意で、q/k/v/o_proj を持つのは残りの 6 層。gate/up/down_proj（MLP）は全層にある
    lora = LoraConfig(r=config["lora_r"], lora_alpha=config["lora_alpha"], lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
                      target_modules=TARGET_MODULES)
    USE_AMP = False
    sft_args = dict(output_dir=str(work / "ckpt"), num_train_epochs=config["num_train_epochs"], per_device_train_batch_size=4, gradient_accumulation_steps=2,
                    learning_rate=config["lr"], lr_scheduler_type="cosine", warmup_steps=config["warmup_steps"], logging_steps=10, save_steps=10, save_total_limit=2,
                    fp16=USE_AMP, max_length=config["max_seq_len"], packing=False, report_to="none", seed=config["seed"])
    if smoke:  # 動作確認のときだけ 2 ステップで止める。本番はノートブックと同じ引数だけを渡す
        sft_args.update(max_steps=2, logging_steps=1, save_strategy="no", use_cpu=device == "cpu")
    sft = SFTConfig(**sft_args)
    trainer = SFTTrainer(model=model, args=sft, train_dataset=train_ds, eval_dataset=valid_ds, peft_config=lora, processing_class=tok)
    trainer.model.print_trainable_parameters()   # LoRA で学習するパラメータの割合
    trainable, total = trainer.model.get_nb_trainable_parameters()
    t0 = time.time()
    output = trainer.train()
    seconds = time.time() - t0
    print(f"学習時間: {seconds:.0f} 秒 | ステップ数: {trainer.state.global_step} | エポック: {trainer.state.epoch:.1f}", flush=True)
    # ここからはノートブックに無い記録。valid は学習中には評価されない（SFTConfig の eval_strategy が既定の "no"）ので、学習後に 1 回だけ loss を測る
    valid_loss = trainer.evaluate()["eval_loss"] if valid_ds is not None else None
    logged = [h for h in trainer.state.log_history if "loss" in h]
    info = {"seconds": round(seconds, 1), "global_step": trainer.state.global_step, "epoch": trainer.state.epoch,
            "train_loss": output.training_loss, "final_logged_loss": logged[-1]["loss"] if logged else None, "valid_loss": valid_loss,
            "trainable_params": trainable, "all_params": total, "trainable_percent": round(100 * trainable / total, 4),
            "log_history": trainer.state.log_history}
    print("train:", json.dumps({k: v for k, v in info.items() if k != "log_history"}, ensure_ascii=False), flush=True)
    trainer.model.save_pretrained(work / "adapter")
    tuned = trainer.model
    tuned.config.use_cache = True
    tuned.eval()  # 学習モードのままだと dropout が効き、評価の出力が揺れる
    return tuned, info


def env_info(device: str) -> dict:
    import accelerate, datasets, peft, torch, transformers, trl

    try:
        commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        commit = None
    return {"device": device, "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "python": platform.python_version(), "platform": platform.platform(),
            "versions": {m.__name__: m.__version__ for m in [transformers, peft, trl, accelerate, datasets, torch]},
            "commit": commit, "finished_at": datetime.now().astimezone().isoformat(timespec="seconds")}


def run_faq(name: str, out: Path, work: Path, smoke: bool, device):
    import peft, torch, transformers, trl

    spec = RUNS[name]
    config = {**BASE_CONFIG, **spec["config"]}
    data = lora_data.FAQ_SETS[spec["data"]]
    splits = lora_data.build_splits(data)
    train, valid, test, gold = splits["train"], splits["valid"], splits["test"], splits["gold"]
    system = data["system"]
    knowledge_questions = data["knowledge_questions"]
    if smoke:
        test, knowledge_questions = test[:2] + test[-1:], knowledge_questions[:1]  # 根拠あり 2 問・根拠なし 1 問・知識質問 1 問
        config["max_new_tokens"] = 48
    print(json.dumps(config, ensure_ascii=False, indent=2))
    print(f"train={len(train)} valid={len(valid)} test={len(test)} gold={len(gold)}")
    print("学習例の 1 件 | 質問:", train[0]["question"], "| 望ましい出力:", train[0]["target"], flush=True)
    for fname, rows in [("train.jsonl", train), ("test.jsonl", test)]:
        (work / fname).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    (work / "gold.json").write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")

    tok, model, device = load_model(config, device)
    gen = lambda m: (lambda ex: generate(m, tok, build_messages(ex, system), config))
    before_summary, before_rows = evaluate(gen(model), test, gold, "before", out)
    tuned, train_info = train_lora(model, tok, [to_chat(e, system) for e in train], [to_chat(e, system) for e in valid], config, work, smoke, device)
    after_summary, after_rows = evaluate(gen(tuned), test, gold, "after", out)
    # 学習前は形式も内容も通ったのに、学習後に落ちた質問（退行）
    regressed = [b["question"] for b, a in zip(before_rows, after_rows) if b["both_ok"] and not a["both_ok"]]
    print("退行:", regressed, flush=True)

    knowledge_rows = []
    for q in knowledge_questions:
        ex = lora_data.make_example(q, "", True, splits["faq_text"])
        # 学習前の出力は adapter を一時的に無効にして取る（ノートブックのセクション 6 と同じ）
        with tuned.disable_adapter():
            before_raw = gen(tuned)(ex)
        after_raw = gen(tuned)(ex)
        knowledge_rows.append({"質問": q, "FAQ にある": q in gold, "学習前の分類": classify(before_raw), "学習前の出力": before_raw,
                               "学習後の分類": classify(after_raw), "学習後の出力": after_raw})
    print("知識質問:", json.dumps([{k: r[k] for k in ("質問", "学習前の分類", "学習後の分類")} for r in knowledge_rows], ensure_ascii=False), flush=True)

    result = {
        "config": config,
        "versions": {m.__name__: m.__version__ for m in [transformers, peft, trl, torch]},
        "method": "LoRA（量子化なし）",
        "before": before_summary, "after": after_summary,
        "regressed": regressed,
        "knowledge": knowledge_rows,
        "executed_training_myself": True,
        # ここから下はノートブックに無い項目
        "run": name, "data": spec["data"], "note": spec["note"], "smoke": smoke,
        "train": train_info,
        "env": env_info(device),
    }
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("knowledge", "train")}, ensure_ascii=False, indent=2), flush=True)


# ---- 発展: 用語集の SFT と、用語集の検索との比較 ----

def search_hits(result: str) -> list[dict]:
    return json.loads(result) if result.startswith("[") else []


def timed(fn):
    t0 = time.time()
    value = fn()
    return value, round(time.time() - t0, 1)


def glossary_rows(items, answers, label, out: Path, seconds=None, extra=None):
    from app.tools import load_glossary

    definitions = {t["id"]: t["definition"] for t in load_glossary()}
    rows = []
    for i, (item, answer) in enumerate(zip(items, answers)):
        row = {"category": item["category"], "kind": item.get("kind"), "question": item["question"], "term_id": item["term_id"],
               "answer": answer, "ok": lora_data.score_glossary_answer(answer, item), "abstained": lora_data.abstained(answer)}
        if item["term_id"]:
            # 用語集の定義にどれだけ近いか（1.0 なら一字一句同じ）。学習で定義を丸暗記したかの目安
            row["similarity"] = round(difflib.SequenceMatcher(None, lora_data.normalize(answer), lora_data.normalize(definitions[item["term_id"]])).ratio(), 3)
        if extra: row.update(extra[i])
        rows.append(row)
    summary = {"label": label, "n": len(rows), "accuracy": sum(r["ok"] for r in rows) / len(rows), "seconds": seconds, "by_category": {}}
    for cat in lora_data.GLOSSARY_CATEGORIES:
        sub = [r for r in rows if r["category"] == cat]
        if sub:
            summary["by_category"][cat] = {"n": len(sub), "accuracy": sum(r["ok"] for r in sub) / len(sub),
                                           "abstained": sum(r["abstained"] for r in sub) / len(sub)}
    (out / f"eval_{label}.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(label, json.dumps(summary, ensure_ascii=False), flush=True)
    return summary, rows


def run_glossary(name: str, out: Path, work: Path, smoke: bool, device):
    import peft, torch, transformers, trl
    from app.tools import load_glossary, search_glossary

    term_ids = {t["term"]: t["id"] for t in load_glossary()}
    spec = RUNS[name]
    config = {**BASE_CONFIG, **spec["config"]}
    records = [json.loads(line) for line in GLOSSARY_SFT.read_text(encoding="utf-8").splitlines() if line.strip()]
    items = lora_data.GLOSSARY_EVAL
    if smoke:
        items = [next(i for i in items if i["category"] == c) for c in lora_data.GLOSSARY_CATEGORIES]  # 各カテゴリ 1 問
        config["max_new_tokens"] = 48
    print(json.dumps(config, ensure_ascii=False, indent=2))
    print(f"SFT データ={len(records)} 件 | 評価={len(items)} 問 | 学習例の 1 件:", json.dumps(records[0], ensure_ascii=False), flush=True)

    # 検索だけ: 用語集の検索ツール（app/tools.py）に検索語を渡し、返ってきた用語が正解か（C は「見つかりませんでした」か）を見る
    search_rows = []
    for item in items:
        query = lora_data.search_query(item["question"])
        result = search_glossary(query)
        hit_ids = [term_ids[h["term"]] for h in search_hits(result)]
        ok = (not hit_ids) if item["category"] == "C" else item["term_id"] in hit_ids
        search_rows.append({"category": item["category"], "kind": item.get("kind"), "question": item["question"], "query": query,
                            "term_id": item["term_id"], "hit_ids": hit_ids, "ok": ok, "result": result})
    search_summary = {"label": "search", "n": len(search_rows), "accuracy": sum(r["ok"] for r in search_rows) / len(search_rows), "by_category": {}}
    for cat in lora_data.GLOSSARY_CATEGORIES:
        sub = [r for r in search_rows if r["category"] == cat]
        if sub:
            search_summary["by_category"][cat] = {"n": len(sub), "accuracy": sum(r["ok"] for r in sub) / len(sub)}
    (out / "search.json").write_text(json.dumps({"summary": search_summary, "rows": search_rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("search", json.dumps(search_summary, ensure_ascii=False), flush=True)

    tok, model, device = load_model(config, device)
    ask = lambda m, messages: generate(m, tok, messages, config)
    # 学習データと同じ形（system なし、user に質問だけ）で聞く
    answers, seconds = timed(lambda: [ask(model, [{"role": "user", "content": i["question"]}]) for i in items])
    before_summary, _ = glossary_rows(items, answers, "before", out, seconds)
    # 検索＋素のモデル: 検索結果をプロンプトに入れて、学習していないモデルに答えさせる
    answers, seconds = timed(lambda: [ask(model, [{"role": "system", "content": lora_data.RAG_SYSTEM},
                                                  {"role": "user", "content": f"検索結果:\n{r['result']}\n\n質問: {i['question']}"}])
                                      for i, r in zip(items, search_rows)])
    rag_summary, _ = glossary_rows(items, answers, "rag", out, seconds, extra=[{"query": r["query"], "hit_ids": r["hit_ids"]} for r in search_rows])

    # 学習: スクリプトの出力（116 件）をそのまま使う。valid は作らない
    tuned, train_info = train_lora(model, tok, records, None, config, work, smoke, device)
    answers, seconds = timed(lambda: [ask(tuned, [{"role": "user", "content": i["question"]}]) for i in items])
    after_summary, _ = glossary_rows(items, answers, "after", out, seconds)

    result = {
        "config": config,
        "versions": {m.__name__: m.__version__ for m in [transformers, peft, trl, torch]},
        "method": "LoRA（量子化なし）",
        "before": before_summary, "after": after_summary, "rag": rag_summary, "search": search_summary,
        "executed_training_myself": True,
        "run": name, "data": spec["data"], "note": spec["note"], "smoke": smoke,
        "sft_data": {"path": str(GLOSSARY_SFT.relative_to(ROOT)), "records": len(records)},
        "train": train_info,
        "env": env_info(device),
    }
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "train"}, ensure_ascii=False, indent=2), flush=True)


# ---- 集計（torch 不要） ----

def failure_type(row: dict, kind: str | None = None) -> str:
    """形式か内容で落ちた出力を型に分ける。kind は暗号資産取引所の根拠なしの質問の種類（near / out）。"""
    ok, reason, obj = check_format(row["raw"])
    loose = loose_parse(row["raw"], ok, obj)
    needs_review = loose.get("needs_review") if loose else None
    parts = [] if ok else [f"形式の崩れ（{reason}）"]
    if not isinstance(needs_review, bool):  # needs_review が読めないので、判断の型は分からない
        return parts[0]
    if row["gold_needs_review"] and not needs_review:
        parts.append("根拠なしに断定" + (f"（{'ニアミス' if kind == 'near' else '範囲外'}）" if kind else ""))
    elif not row["gold_needs_review"] and needs_review:
        parts.append("根拠ありで逃げた")
    elif not row["content_ok"]:
        parts.append("語句が違う")
    return "＋".join(parts)


def load_results(results_dir: Path) -> dict:
    out = {}
    for path in sorted(results_dir.glob("*/result.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        out[path.parent.name] = (path.parent, result)
    return out


def pct(x) -> str:
    return "—" if x is None else f"{x:.2f}"


def summary(results_dir: Path = RESULTS) -> str:
    results = load_results(results_dir)
    lines = []
    faq_runs = [(n, d, r) for n, (d, r) in results.items() if r.get("data") != "glossary"]
    order = list(RUNS)
    faq_runs.sort(key=lambda x: order.index(x[0]) if x[0] in order else len(order))
    if faq_runs:
        lines += ["**FAQ のラン：学習前 → 学習後**", "",
                  "| ラン | 変えたもの | format_rate | content_rate | both_rate | 退行 | 最終 loss | 平均 loss | valid loss | 学習時間（秒） | ステップ | trainable% | GPU |",
                  "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
        for name, _, r in faq_runs:
            t, b, a = r["train"], r["before"], r["after"]
            loss = lambda key: "—" if t.get(key) is None else f"{t[key]:.4f}"
            lines.append(f"| {name} | {r['note']} | {pct(b['format_rate'])} → {pct(a['format_rate'])} | {pct(b['content_rate'])} → {pct(a['content_rate'])} | "
                         f"{pct(b['both_rate'])} → {pct(a['both_rate'])} | {len(r['regressed'])} | {loss('final_logged_loss')} | {loss('train_loss')} | {loss('valid_loss')} | "
                         f"{t['seconds']} | {t['global_step']} | {t['trainable_percent']} | {r['env']['gpu'] or r['env']['device']} |")
        lines += ["", "**loss の推移（10 ステップごとの記録）**", "", "| ラン | " + " | ".join(f"step {s}" for s in range(10, 41, 10)) + " |", "|---|" + "---:|" * 4]
        for name, _, r in faq_runs:
            losses = {h["step"]: h["loss"] for h in r.get("train", {}).get("log_history", []) if "loss" in h}
            lines.append(f"| {name} | " + " | ".join(f"{losses[s]:.4f}" if s in losses else "—" for s in range(10, 41, 10)) + " |")
        lines += ["", "**学習前・学習後の失敗の型**（21 問のうち、形式か内容で落ちたもの）", "",
                  "| ラン | 学習前 | 学習後 |", "|---|---|---|"]
        for name, d, r in faq_runs:
            kinds = lora_data.CRYPTO_UNGROUNDED_KIND if r.get("data") == "crypto" else {}
            cells = []
            for label in ("before", "after"):
                rows = json.loads((d / f"eval_{label}.json").read_text(encoding="utf-8"))["rows"]
                counts = {}
                for row in rows:
                    if not row["both_ok"]:
                        ft = failure_type(row, kinds.get(row["question"]))
                        counts[ft] = counts.get(ft, 0) + 1
                cells.append("、".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])) or "なし")
            lines.append(f"| {name} | {cells[0]} | {cells[1]} |")
        lines += ["", "**知識を問う質問（学習前の分類 → 学習後の分類）**", "", "| ラン | " + " | ".join(f"Q{i}" for i in range(1, 5)) + " |", "|---|" + "---|" * 4]
        for name, _, r in faq_runs:
            lines.append(f"| {name} | " + " | ".join(f"{k['学習前の分類']} → {k['学習後の分類']}" for k in r["knowledge"]) + " |")
        questions = {r["data"]: [k["質問"] for k in r["knowledge"]] for _, _, r in faq_runs}
        for data, qs in questions.items():
            lines.append("")
            lines.append(f"- {data} の Q1〜Q4：" + " / ".join(qs))

    for name, (d, r) in results.items():
        if r.get("data") != "glossary":
            continue
        t = r["train"]
        lines += ["", f"**発展（{name}）：条件ごとの正解率**（学習 {t['global_step']} ステップ、{t['seconds']} 秒、最終 loss {t['final_logged_loss']:.4f}、{r['env']['gpu'] or r['env']['device']}）", "",
                  "| カテゴリ | 問題数 | 学習前（素のモデル） | 学習後（LoRA） | 検索だけ | 検索＋素のモデル |", "|---|---:|---:|---:|---:|---:|"]
        for cat, cat_name in lora_data.GLOSSARY_CATEGORIES.items():
            n = r["before"]["by_category"].get(cat, {}).get("n")
            if n:
                cells = [pct(r[c]["by_category"][cat]["accuracy"]) for c in ("before", "after", "search", "rag")]
                lines.append(f"| {cat}：{cat_name} | {n} | " + " | ".join(cells) + " |")
        lines.append(f"| 全体 | {r['before']['n']} | " + " | ".join(pct(r[c]["accuracy"]) for c in ("before", "after", "search", "rag")) + " |")
    return "\n".join(lines)


def detail(name: str, results_dir: Path = RESULTS) -> str:
    d, r = load_results(results_dir)[name]
    if r.get("data") == "glossary":
        evals = {label: json.loads((d / f"eval_{label}.json").read_text(encoding="utf-8"))["rows"] for label in ("before", "rag", "after")}
        search = json.loads((d / "search.json").read_text(encoding="utf-8"))["rows"]
        lines = ["| カテゴリ | 質問 | 学習前 | 学習後 | 検索 | 検索＋素のモデル |", "|---|---|---|---|---|---|"]
        for i, s in enumerate(search):
            cell = lambda row: f"{'○' if row['ok'] else '×'} {row['answer'][:80].replace('|', '｜').replace(chr(10), ' ')}"
            lines.append(f"| {s['category']} | {s['question']} | {cell(evals['before'][i])} | {cell(evals['after'][i])} | "
                         f"{'○' if s['ok'] else '×'} {', '.join(s['hit_ids']) or '見つからず'} | {cell(evals['rag'][i])} |")
        return "\n".join(lines)
    kinds = lora_data.CRYPTO_UNGROUNDED_KIND if r.get("data") == "crypto" else {}
    before = json.loads((d / "eval_before.json").read_text(encoding="utf-8"))["rows"]
    after = json.loads((d / "eval_after.json").read_text(encoding="utf-8"))["rows"]
    mark = lambda row: f"{'○' if row['format_ok'] else '×'}/{'○' if row['content_ok'] else '×'}"
    lines = ["| 質問 | 正解の needs_review | 学習前の出力 | 前 形式/内容 | 学習後の出力 | 後 形式/内容 | 学習後の失敗の型 |", "|---|---|---|---|---|---|---|"]
    for b, a in zip(before, after):
        esc = lambda s: s.replace("|", "｜").replace("\n", " ")
        lines.append(f"| {b['question']} | {b['gold_needs_review']} | {esc(b['raw'])} | {mark(b)} | {esc(a['raw'])} | {mark(a)} | "
                     f"{'' if a['both_ok'] else failure_type(a, kinds.get(a['question']))} |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", choices=list(RUNS), help="実行するラン")
    parser.add_argument("--out", type=Path, help="result.json と eval_*.json の保存先")
    parser.add_argument("--work", type=Path, help="チェックポイントと adapter の置き場（既定: <一時ディレクトリ>/lec02_work/<ラン>）")
    parser.add_argument("--device", choices=["cuda", "mps", "cpu"], help="既定はノートブックと同じく cuda → mps → cpu の順に自動で選ぶ")
    parser.add_argument("--smoke", action="store_true", help="動作確認用。2 ステップだけ学習し、数問だけ評価する")
    parser.add_argument("--summary", action="store_true", help="lectures/02/results/*/result.json を Markdown の表にする")
    parser.add_argument("--detail", metavar="RUN", help="1 つのランの、質問ごとの出力を表にする")
    parser.add_argument("--results", type=Path, default=RESULTS, help="--summary と --detail で読むディレクトリ")
    args = parser.parse_args()

    if args.summary:
        print(summary(args.results))
        return
    if args.detail:
        print(detail(args.detail, args.results))
        return
    if not args.run or not args.out:
        parser.error("--run と --out を指定してください（集計は --summary）")
    args.out.mkdir(parents=True, exist_ok=True)
    # チェックポイントと adapter は結果と分けて置く（Drive や repo に大きなファイルを置かないため）
    work = args.work or Path(tempfile.gettempdir()) / "lec02_work" / args.run
    work.mkdir(parents=True, exist_ok=True)
    print(f"=== {args.run}: {RUNS[args.run]['note']} | Python {sys.version.split()[0]} ===", flush=True)
    (run_glossary if RUNS[args.run]["data"] == "glossary" else run_faq)(args.run, args.out, work, args.smoke, args.device)


if __name__ == "__main__":
    main()
