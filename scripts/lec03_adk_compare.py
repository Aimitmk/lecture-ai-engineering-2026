"""第3回 宿題（発展 a）: ADK 版（adk_agent/glossary_agent）に演習と同じ質問を投げ、Pydantic AI 版と比べる。

adk run に --jsonl を付けると、モデルの応答（ツール呼び出しを含む）とツールの戻り値が、
1つずつイベントとして JSON の行で出る。それを results/adk/runs/ にそのまま保存し、
ツール呼び出しと回答を抜き出して、基礎の baseline（Pydantic AI 版、results/basic/runs.jsonl）と並べる。

使い方（リポジトリの直下で）:
    PYTHONPATH=. uv run --frozen --env-file .env --with google-adk python -m scripts.lec03_adk_compare --run
    uv run --frozen python -m scripts.lec03_adk_compare --summary
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "lectures" / "03" / "results" / "adk"
RAW_DIR = OUT_DIR / "runs"
INDEX = OUT_DIR / "runs.jsonl"
BASIC_RUNS = ROOT / "lectures" / "03" / "results" / "basic" / "runs.jsonl"
AGENT_DIR = "adk_agent/glossary_agent"

# 基礎の baseline と同じ質問（scripts/lec03_prompt_variants.py の QUESTIONS）
QUESTIONS = {
    "3levels": "AIE2026の講座の宿題にある「3レベル」とは何ですか？",
    "lora_qlora": "LoRAとQLoRAの違いは？",
    "quiz": "第2回の内容から確認問題を1問出して",
}


def _events(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def _parts(event: dict) -> list[dict]:
    content = event.get("content") or {}
    return content.get("parts") or []


def _get(d: dict, camel: str, snake: str):
    """ADK の JSONL は camelCase（functionCall など）。念のため snake_case も読む。"""
    return d.get(camel, d.get(snake))


def extract(events: list[dict]) -> dict:
    """イベントの列から、ツール呼び出し・モデルの応答回数・トークン・最終回答を取り出す。"""
    calls, model_turns, prompt_tokens, output_tokens, texts, errors = [], 0, 0, 0, [], []
    models = set()
    for event in events:
        code, message = _get(event, "errorCode", "error_code"), _get(event, "errorMessage", "error_message")
        if code or message:
            errors.append({"code": code, "message": str(message)[:300]})
        role = (event.get("content") or {}).get("role")
        if role == "model":
            model_turns += 1
            models.add(_get(event, "modelVersion", "model_version"))
            usage = _get(event, "usageMetadata", "usage_metadata") or {}
            prompt_tokens += _get(usage, "promptTokenCount", "prompt_token_count") or 0
            output_tokens += (_get(usage, "candidatesTokenCount", "candidates_token_count") or 0) + (
                _get(usage, "thoughtsTokenCount", "thoughts_token_count") or 0
            )
        for part in _parts(event):
            call = _get(part, "functionCall", "function_call")
            if call:
                calls.append({"tool": call.get("name"), "args": call.get("args") or {}})
            elif part.get("text") and role == "model" and not part.get("thought"):
                texts.append(part["text"])
    return {
        "tool_calls": calls,
        "model_turns": model_turns,
        "model_versions": sorted(m for m in models if m),
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "output": texts[-1] if texts else "",
        "errors": errors,
    }


def _mask(text: str) -> str:
    """adk run が最初に出すログの場所（ローカルの一時フォルダ）を伏せる。"""
    return re.sub(r"/(?:private/)?var/folders/[^\s]*/T/", "<TMPDIR>/", text)


def run_once(adk: str, qid: str, trial: int, version: str) -> dict:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    record = {"question_id": qid, "question": QUESTIONS[qid], "trial": trial, "adk_version": version, "attempts": []}
    for attempt in range(1, 4):
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        started = time.perf_counter()
        proc = subprocess.run(
            [adk, "run", "--jsonl", "--in_memory", AGENT_DIR, QUESTIONS[qid]],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
        )
        elapsed = round(time.perf_counter() - started, 2)
        raw = RAW_DIR / f"{qid}_{trial}.jsonl"
        raw.write_text(_mask(proc.stdout), encoding="utf-8")
        if proc.stderr.strip():
            raw.with_suffix(".stderr.txt").write_text(_mask(proc.stderr), encoding="utf-8")
        summary = extract(_events(proc.stdout))
        record.update(started_at=started_at, elapsed_s=elapsed, returncode=proc.returncode, raw=raw.name, **summary)
        failed = proc.returncode != 0 or summary["errors"] or not summary["output"]
        record["attempts"].append(
            {"attempt": attempt, "started_at": started_at, "returncode": proc.returncode, "errors": summary["errors"]}
        )
        if not failed:
            record["failed"] = False
            return record
        print(f"    失敗（returncode={proc.returncode}, errors={summary['errors']}）: 65 秒待って再試行", flush=True)
        time.sleep(65)
    record["failed"] = True
    return record


def run(args) -> None:
    adk = shutil.which("adk")
    if adk is None:
        raise SystemExit("adk が見つかりません。uv run --with google-adk で実行してください")
    from google.adk import __version__ as version

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    done = set()
    if INDEX.exists():
        done = {(r["question_id"], r["trial"]) for r in map(json.loads, INDEX.read_text(encoding="utf-8").splitlines()) if not r["failed"]}
    todo = [(qid, t) for t in range(1, args.trials + 1) for qid in args.questions if (qid, t) not in done]
    print(f"[adk] google-adk {version} / 実行 {len(todo)} 回（済み {len(done)} 回）", flush=True)
    for i, (qid, trial) in enumerate(todo, 1):
        record = run_once(adk, qid, trial, version)
        with INDEX.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        calls = ", ".join(f"{c['tool']}({c['args']})" for c in record.get("tool_calls", []))
        status = "失敗" if record["failed"] else f"model_turns={record['model_turns']} {calls}"
        print(f"  {i}/{len(todo)} {qid} #{trial}: {status}", flush=True)
        if i < len(todo):
            time.sleep(args.interval)


def _calls_text(calls: list[dict]) -> str:
    if not calls:
        return "（なし）"
    return "<br>".join(f"`{c['tool']}({', '.join(f'{k}={v!r}' for k, v in c['args'].items())})`" for c in calls)


def _latest(path: Path, keep) -> dict:
    latest = {}
    if path.exists():
        for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()):
            if keep(r):
                latest[(r["question_id"], r["trial"])] = r
    return latest


def summary() -> None:
    adk = _latest(INDEX, lambda r: not r["failed"])
    pai = _latest(BASIC_RUNS, lambda r: not r.get("failed") and r["condition"] == "baseline")
    print("| 質問 | 回 | Pydantic AI 版のツール呼び出し | requests | ADK 版のツール呼び出し | モデルの応答 |")
    print("|---|---:|---|---:|---|---:|")
    for key in sorted(set(adk) | set(pai), key=lambda k: (list(QUESTIONS).index(k[0]), k[1])):
        p, a = pai.get(key), adk.get(key)
        print(
            f"| {key[0]} | {key[1]} | {_calls_text(p['tool_calls']) if p else '－'} | {p['requests'] if p else '－'} "
            f"| {_calls_text(a['tool_calls']) if a else '－'} | {a['model_turns'] if a else '－'} |"
        )
    lines = ["# 第3回 宿題（発展 a）ADK 版の回答", "", "`scripts/lec03_adk_compare.py --summary` で runs.jsonl から作った。", ""]
    for key in sorted(adk, key=lambda k: (list(QUESTIONS).index(k[0]), k[1])):
        a = adk[key]
        lines += [
            f"## {key[0]} / {key[1]} 回目（google-adk {a['adk_version']}、{a['started_at']}、{a['elapsed_s']} 秒）",
            "",
            f"- 質問：{a['question']}",
            f"- ツール呼び出し：{_calls_text(a['tool_calls'])}",
            f"- モデルの応答：{a['model_turns']} 回、入力 {a['prompt_tokens']:,} / 出力 {a['output_tokens']:,} tokens",
            f"- 生のイベント：[runs/{a['raw']}](runs/{a['raw']})",
            "",
            "```text",
            a["output"].strip(),
            "```",
            "",
        ]
    (OUT_DIR / "answers.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="第3回 宿題（発展 a）: ADK 版に同じ質問を投げて比べる")
    parser.add_argument("--run", action="store_true", help="adk run --jsonl で質問し、results/adk/ に保存する（済みの組はとばす）")
    parser.add_argument("--summary", action="store_true", help="Pydantic AI 版と並べた表を出し、answers.md を作る")
    parser.add_argument("--questions", nargs="+", default=list(QUESTIONS), choices=list(QUESTIONS))
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--interval", type=float, default=12.0)
    args = parser.parse_args()
    if not (args.run or args.summary):
        parser.error("--run か --summary を指定してください")
    if args.run:
        run(args)
    if args.summary:
        summary()


if __name__ == "__main__":
    main()
