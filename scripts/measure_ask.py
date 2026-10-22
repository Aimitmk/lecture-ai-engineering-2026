"""第1回 宿題（基礎・発展）: 同じ質問を繰り返し送り、回答・応答時間・トークン数を記録する。

使い方（モデルは app.ask と同じく環境変数 AIE_MODEL で選ぶ。APIキーは .env から読む）:
    uv run --env-file .env python -m scripts.measure_ask --list-models
    uv run --env-file .env python -m scripts.measure_ask --tag models --runs 3 --interval 5
    AIE_MODEL=gemini-3.8-flash uv run --env-file .env python -m scripts.measure_ask --questions general course --interval 15
    uv run --env-file .env python -m scripts.measure_ask --tag temperature --questions course --temperature 0
    uv run --env-file .env python -m scripts.measure_ask --tag burst --questions short --runs 20 --interval 0
    uv run python -m scripts.measure_ask --summary   # 集計して Markdown の表を出す（APIキー不要）

結果は1回ごとに lectures/01/results/runs.jsonl へ追記するので、途中で 429 や 503 が出ても、
それまでの結果は残る。429（レート制限）が出たら、続けても失敗するだけなので止める。
google-genai は既定では自動で再試行しないので、応答時間は1回の呼び出しにかかった時間になる。
"""

import argparse
import difflib
import itertools
import json
import statistics
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import httpx
from google import genai
from google.genai import errors, types

from app.ask import DEFAULT_QUESTION, build_config
from app.config import MODEL, get_api_key

RESULTS = Path(__file__).resolve().parent.parent / "lectures" / "01" / "results" / "runs.jsonl"

# 回答の長さが違う3種類の質問（short: 一言で済む、general: 一般的な用語、course: 講座に固有のこと）
QUESTIONS = {
    "short": "日本の首都はどこですか？一言で答えてください。",
    "general": "LoRAとは何ですか？",
    "course": DEFAULT_QUESTION,
}


def error_info(e: errors.APIError) -> dict:
    """APIエラーを記録用の dict にする。429 なら、どの上限に当たったかと、待つべき時間も取り出す。"""
    info = {"code": e.code, "status": e.status, "message": (e.message or "")[:300]}
    body = e.details if isinstance(e.details, dict) else {}
    details = body.get("error", {}).get("details", [])  # 503 などでは無いこともある
    for d in details if isinstance(details, list) else []:
        kind = str(d.get("@type", ""))
        if kind.endswith("QuotaFailure"):
            info["quota"] = [
                {k: v.get(k) for k in ("quotaId", "quotaValue", "quotaMetric")}
                for v in d.get("violations", [])
            ]
        elif kind.endswith("RetryInfo"):
            info["retry_delay"] = d.get("retryDelay")
    return info


def measure_once(client: genai.Client, question_id: str, temperature: float | None) -> dict:
    """1回だけ質問し、応答時間・トークン数・回答（またはエラー）を dict にする。"""
    start = time.perf_counter()
    try:
        response = client.models.generate_content(
            model=MODEL, contents=QUESTIONS[question_id], config=build_config(temperature)
        )
    except errors.APIError as e:
        return {"latency_s": round(time.perf_counter() - start, 3), "error": error_info(e)}
    except httpx.HTTPError as e:  # タイムアウトや接続エラー
        error = {"type": type(e).__name__, "message": str(e)[:300]}
        return {"latency_s": round(time.perf_counter() - start, 3), "error": error}
    latency = time.perf_counter() - start

    usage = response.usage_metadata or types.GenerateContentResponseUsageMetadata()
    candidate = response.candidates[0] if response.candidates else None
    return {
        "latency_s": round(latency, 3),
        "model_version": response.model_version,  # 実際に応答したモデル
        "prompt_tokens": usage.prompt_token_count or 0,
        "output_tokens": usage.candidates_token_count or 0,
        "thoughts_tokens": usage.thoughts_token_count or 0,
        "total_tokens": usage.total_token_count or 0,
        "finish_reason": candidate.finish_reason.value if candidate and candidate.finish_reason else None,
        "text": response.text,
    }


def describe(row: dict) -> str:
    head = f"[{row['question']} #{row['run']}] {row['latency_s']:.2f}s"
    if "error" in row:
        e = row["error"]
        return f"{head} エラー {e.get('code', e.get('type'))} {e.get('status') or ''} {e.get('message', '')[:100]}"
    return (
        f"{head} 入力 {row['prompt_tokens']} / 出力 {row['output_tokens']} / 思考 {row['thoughts_tokens']}"
        f" / 合計 {row['total_tokens']}（{row['model_version']}、{len(row['text'] or '')}文字）"
    )


def run(args: argparse.Namespace) -> None:
    client = genai.Client(api_key=get_api_key())
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    batch = datetime.now().astimezone().isoformat(timespec="seconds")  # この実行をまとめる印
    print(f"[model] {MODEL}  [tag] {args.tag}  [temperature] {args.temperature}  [interval] {args.interval}s")

    started = time.perf_counter()
    # 1回目・2回目…ごとに質問を一巡させる（時間による揺れが特定の質問に偏らないように）
    jobs = [(run_no, q) for run_no in range(1, args.runs + 1) for q in args.questions]
    for i, (run_no, question_id) in enumerate(jobs):
        if i > 0:
            time.sleep(args.interval)
        row = {
            "batch": batch,
            "tag": args.tag,
            "model": MODEL,
            "temperature": args.temperature,
            "question": question_id,
            "run": run_no,
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "t_s": round(time.perf_counter() - started, 3),  # この実行を始めてからの秒数
        }
        row.update(measure_once(client, question_id, args.temperature))
        with RESULTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(describe(row), flush=True)  # ファイルにリダイレクトしても途中経過が見えるように
        if row.get("error", {}).get("code") == 429:
            print("レート制限（429）に達したので止めます。")
            break


def list_models() -> None:
    """generateContent に使えるモデルの一覧。temperature の既定値・最大値と、思考するかも出す。"""
    client = genai.Client(api_key=get_api_key())
    print("| モデル | 入力上限 | 出力上限 | temperature 既定 | 最大 | thinking |")
    print("|---|---:|---:|---:|---:|---|")
    for m in client.models.list():
        if "generateContent" not in (m.supported_actions or []):
            continue
        print(
            f"| {m.name} | {m.input_token_limit} | {m.output_token_limit}"
            f" | {m.temperature} | {m.max_temperature} | {m.thinking} |"
        )


def similarity(texts: list[str]) -> float | None:
    """回答どうしの類似度の平均（1.0 なら一字一句同じ）。回答が2つ未満なら None。"""
    pairs = list(itertools.combinations(texts, 2))
    if not pairs:
        return None
    return statistics.mean(difflib.SequenceMatcher(None, a, b).ratio() for a, b in pairs)


def summarize(rows: list[dict]) -> None:
    groups = defaultdict(list)
    for r in rows:
        if r["tag"] != "burst":
            groups[(r["tag"], r["model"], r["temperature"], r["question"])].append(r)

    print("### モデル・質問ごとの集計\n")
    print(
        "| tag | モデル | temperature | 質問 | 成功/回数 | 応答時間 平均（最小〜最大）秒 | 入力 | 出力 | 思考 | 合計"
        " | (出力+思考)/秒 | 異なる回答 | 類似度 | 回答の文字数 | model_version |"
    )
    print("|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|")
    for (tag, model, temperature, question), rs in groups.items():
        temperature = "既定" if temperature is None else temperature
        ok = [r for r in rs if "error" not in r]
        if not ok:
            print(f"| {tag} | {model} | {temperature} | {question} | 0/{len(rs)} |" + " — |" * 10)
            continue
        latencies = [r["latency_s"] for r in ok]
        texts = [r["text"] or "" for r in ok]
        sim = similarity(texts)
        generated = sum(r["output_tokens"] + r["thoughts_tokens"] for r in ok)
        speed = generated / sum(latencies) if sum(latencies) else 0
        print(
            f"| {tag} | {model} | {temperature} | {question} | {len(ok)}/{len(rs)}"
            f" | {statistics.mean(latencies):.2f}（{min(latencies):.2f}〜{max(latencies):.2f}）"
            + "".join(
                f" | {statistics.mean(r[k] for r in ok):.0f}"
                for k in ("prompt_tokens", "output_tokens", "thoughts_tokens", "total_tokens")
            )
            + f" | {speed:.0f} | {len(set(texts))} | {'—' if sim is None else f'{sim:.2f}'}"
            f" | {min(map(len, texts))}〜{max(map(len, texts))}"
            f" | {', '.join(sorted({r['model_version'] or '?' for r in ok}))} |"
        )

    # 応答時間 = 固定の待ち時間 + 1トークンあたりの生成時間 × トークン数、と見て直線を当てはめる
    print("\n### 応答時間と（出力+思考）トークン数の関係（tag=models）\n")
    points = defaultdict(list)
    for r in rows:
        if r["tag"] == "models" and "error" not in r:
            points[r["model"]].append((r["output_tokens"] + r["thoughts_tokens"], r["latency_s"]))
    for model, pts in points.items():
        xs, ys = zip(*pts)
        if len(set(xs)) < 2 or len(set(ys)) < 2:
            continue
        fit = statistics.linear_regression(xs, ys)
        print(
            f"- {model}: 応答時間 ≈ {fit.intercept:.2f} 秒 + {fit.slope * 1000:.1f} ミリ秒 × トークン数"
            f"（相関係数 {statistics.correlation(xs, ys):.2f}、{len(pts)} 点）"
        )

    errors_ = [r for r in rows if "error" in r]
    print("\n### エラー\n")
    if not errors_:
        print("なし")
    else:
        print("| 時刻 | tag | モデル | 質問 | 回 | code | status | quota（id = 上限） | retry_delay | message |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for r in errors_:
            e = r["error"]
            quota = "<br>".join(f"{q.get('quotaId')} = {q.get('quotaValue')}" for q in e.get("quota", []))
            message = (e.get("message") or "").replace("|", "/").replace("\n", " ")[:120]
            print(
                f"| {r['time']} | {r['tag']} | {r['model']} | {r['question']} | {r['run']}"
                f" | {e.get('code', e.get('type'))} | {e.get('status') or ''} | {quota}"
                f" | {e.get('retry_delay') or ''} | {message} |"
            )

    bursts = defaultdict(list)
    for r in rows:
        if r["tag"] == "burst":
            bursts[(r["batch"], r["model"])].append(r)
    if bursts:
        print("\n### 間隔なしの連続呼び出し（tag=burst）\n")
        print("| 開始 | モデル | 呼び出し | 最初の 429 までの成功 | 最初の 429 の時刻（開始からの秒） | 成功の応答時間 平均 秒 |")
        print("|---|---|---:|---:|---:|---:|")
        for (batch, model), rs in bursts.items():
            first_429 = next((r for r in rs if r.get("error", {}).get("code") == 429), None)
            ok = [r for r in rs if "error" not in r]
            ok_before = [r for r in ok if first_429 is None or r["t_s"] < first_429["t_s"]]
            mean_latency = f"{statistics.mean(r['latency_s'] for r in ok):.2f}" if ok else "—"
            print(
                f"| {batch} | {model} | {len(rs)} | {len(ok_before)}"
                f" | {first_429['t_s'] if first_429 else '429 なし'} | {mean_latency} |"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="応答時間とトークン数を計測する（第1回 宿題）")
    parser.add_argument("--list-models", action="store_true", help="使えるモデルの一覧を表示する")
    parser.add_argument("--summary", action="store_true", help="記録した結果を集計する（APIキー不要）")
    parser.add_argument("--questions", nargs="+", choices=QUESTIONS, default=list(QUESTIONS))
    parser.add_argument("--runs", type=int, default=3, help="各質問を何回ずつ送るか")
    parser.add_argument("--interval", type=float, default=5, help="呼び出しの間隔（秒）。レート制限に合わせる")
    parser.add_argument("--temperature", type=float, help="指定しなければモデルの既定値")
    parser.add_argument("--tag", default="models", help="実験の名前（集計で使う。例: models, temperature, burst）")
    args = parser.parse_args()

    if args.summary:
        if not RESULTS.exists():
            raise SystemExit(f"{RESULTS} がまだありません。先に計測してください。")
        with RESULTS.open(encoding="utf-8") as f:
            summarize([json.loads(line) for line in f if line.strip()])
    elif args.list_models:
        list_models()
    else:
        run(args)


if __name__ == "__main__":
    main()
