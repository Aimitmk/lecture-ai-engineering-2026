"""第3回 宿題（基礎）: INSTRUCTIONS や docstring を1か所だけ変えて、同じ質問への動きを比べる。

app/ のファイルは書き換えず、Agent.override で「モデルに渡す文」だけを差し替える。
差し替えたあとにモデルへ渡る指示とツールの説明文は --dump で書き出し、
元のエージェントとの違いが1か所だけであることを確かめる。

使い方（リポジトリの直下で）:
    uv run --frozen python -m scripts.lec03_prompt_variants --dump                  # APIキー不要
    uv run --frozen --env-file .env python -m scripts.lec03_prompt_variants --run   # runs.jsonl に追記
    uv run --frozen python -m scripts.lec03_prompt_variants --summary               # 表と traces.md
"""

import argparse
import contextlib
import copy
import difflib
import io
import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset

from app.agent import INSTRUCTIONS, agent, build_model, print_trace
from app.config import MODEL

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "lectures" / "03" / "results" / "basic"
RUNS = OUT_DIR / "runs.jsonl"

MUST_SEARCH_LINE = "- 用語や講座に固有のことを答える前に、必ず search_glossary で用語集を確認する。\n"
LECTURE_LINE = "- 回答の最後に、関係する回（第N回）を示す。\n"
QUIZ_LINE = "- 最後に確認問題を1問出す。\n"
ONE_TERM = "query には調べたい用語を1つだけ入れる"
BATCH_TERMS = "query には調べたい用語をまとめて入れる"


def _replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"置き換える文が1か所ではありません: {old!r}")
    return text.replace(old, new)


@dataclass(frozen=True)
class Condition:
    name: str
    change: str  # 何を変えたか
    instructions: str | None = None  # None なら INSTRUCTIONS のまま
    glossary_doc: tuple[str, str] | None = None  # search_glossary の説明文の（変更前, 変更後）


CONDITIONS = [
    Condition("baseline", "変更なし（演習のまま）"),
    Condition(
        "no_must_search",
        "INSTRUCTIONS から「必ず search_glossary で用語集を確認する」の行を消す",
        instructions=_replace_once(INSTRUCTIONS, MUST_SEARCH_LINE, ""),
    ),
    Condition(
        "docstring_batch",
        "search_glossary の docstring の「1つだけ入れる」を「まとめて入れる」にする",
        glossary_doc=(ONE_TERM, BATCH_TERMS),
    ),
    Condition(
        "end_with_quiz",
        "INSTRUCTIONS の「回答の最後に、関係する回（第N回）を示す」を「最後に確認問題を1問出す」にする",
        instructions=_replace_once(INSTRUCTIONS, LECTURE_LINE, QUIZ_LINE),
    ),
]
BY_NAME = {c.name: c for c in CONDITIONS}

QUESTIONS = {
    "3levels": "AIE2026の講座の宿題にある「3レベル」とは何ですか？",
    "lora_qlora": "LoRAとQLoRAの違いは？",
    "quiz": "第2回の内容から確認問題を1問出して",  # baseline だけで使う（発展 a の ADK 版と比べるため）
}
DEFAULT_QUESTIONS = ["3levels", "lora_qlora"]


def registered_tools() -> dict:
    """agent.py で登録したツール（承認の要否などの設定ごと）。"""
    [toolset] = [t for t in agent.toolsets if isinstance(t, FunctionToolset)]
    return toolset.tools


@contextlib.contextmanager
def applied(cond: Condition):
    """条件の文をモデルに渡すように、エージェントを一時的に差し替える。"""
    kwargs = {}
    if cond.instructions is not None:
        kwargs["instructions"] = cond.instructions
    if cond.glossary_doc is not None:
        old, new = cond.glossary_doc
        replaced = []
        for name, tool in registered_tools().items():
            if name == "search_glossary":
                tool = copy.copy(tool)  # 説明文以外（引数・承認の要否など）はそのまま
                tool.description = _replace_once(tool.description, old, new)
            replaced.append(tool)
        kwargs["tools"] = replaced
    with agent.override(**kwargs) if kwargs else contextlib.nullcontext():
        yield


def visible_prompt() -> str:
    """モデルに渡る指示とツール定義を、TestModel（API を呼ばない偽モデル）で取り出す。"""
    model = TestModel(call_tools=[])
    result = agent.run_sync("ツール一覧", model=model)
    request = next(m for m in result.all_messages() if isinstance(m, ModelRequest))
    lines = ["## instructions", request.instructions or "", ""]
    for tool in model.last_model_request_parameters.function_tools:
        schema = json.dumps(tool.parameters_json_schema, ensure_ascii=False, sort_keys=True)
        lines += [f"## tool: {tool.name} (kind={tool.kind})", tool.description or "", f"parameters: {schema}", ""]
    return "\n".join(lines)


def dump() -> None:
    prompts = OUT_DIR / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    shipped = visible_prompt()  # 差し替えなし = agent.py に登録されているとおり
    base = None
    for cond in CONDITIONS:
        with applied(cond):
            text = visible_prompt()
        (prompts / f"{cond.name}.txt").write_text(text, encoding="utf-8")
        if base is None:
            if text != shipped:
                raise SystemExit("baseline が agent.py のエージェントと一致しません")
            base = text
            print(f"[{cond.name}] agent.py のエージェントと同じ（ツール {text.count('## tool:')} 個）")
            continue
        a, b = base.splitlines(), text.splitlines()
        changes = [op for op in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op[0] != "equal"]
        if len(changes) != 1:
            raise SystemExit(f"[{cond.name}] baseline との違いが {len(changes)} か所あります")
        diff = "\n".join(
            difflib.unified_diff(a, b, "baseline", cond.name, n=1, lineterm="")
        )
        (prompts / f"{cond.name}.diff").write_text(diff + "\n", encoding="utf-8")
        print(f"[{cond.name}] baseline との違いは1か所:\n{diff}\n")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def _trace_text(result) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        print_trace(result)
    return buffer.getvalue().strip("\n")


def run_once(cond: Condition, qid: str, trial: int, commit: str) -> dict:
    record = {
        "condition": cond.name, "question_id": qid, "question": QUESTIONS[qid], "trial": trial,
        "model": MODEL, "commit": commit, "errors": [],
    }
    for attempt in range(1, 4):
        record["started_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        started = time.perf_counter()
        try:
            with applied(cond):
                result = agent.run_sync(QUESTIONS[qid], model=build_model())
        except ModelHTTPError as e:
            wait = 65 if e.status_code == 429 else 30
            record["errors"].append({"attempt": attempt, "status": e.status_code, "body": str(e.body)[:300]})
            print(f"    {e.status_code}: {wait} 秒待って再試行", flush=True)
            time.sleep(wait)
            continue
        messages = result.all_messages()
        responses = [m for m in messages if isinstance(m, ModelResponse)]
        usage = result.usage
        record.update(
            elapsed_s=round(time.perf_counter() - started, 2),
            model_name=responses[-1].model_name if responses else None,
            tool_calls=[
                {"tool": p.tool_name, "args": p.args_as_dict()}
                for m in messages for p in m.parts if isinstance(p, ToolCallPart)
            ],
            requests=usage.requests,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            output=str(result.output),
            trace=_trace_text(result),
            failed=False,
        )
        return record
    record["failed"] = True
    return record


def load_runs() -> list[dict]:
    if not RUNS.exists():
        return []
    return [json.loads(line) for line in RUNS.read_text(encoding="utf-8").splitlines() if line.strip()]


def plan(conditions: list[str], questions: list[str], trials: int, quiz_trials: int) -> list[tuple[str, str, int]]:
    """試行ごとに条件を順番に回す（時間帯による混み具合の差が、特定の条件に偏らないように）。"""
    order = []
    for trial in range(1, trials + 1):
        for qid in questions:
            for name in conditions:
                order.append((name, qid, trial))
        if trial <= quiz_trials:
            order.append(("baseline", "quiz", trial))
    return order


def run(args) -> None:
    if _git("status", "--porcelain", "--", "app"):
        raise SystemExit("app/ に commit していない変更があります。baseline を固定するため、先に commit してください")
    commit = _git("rev-parse", "--short", "HEAD")
    done = {(r["condition"], r["question_id"], r["trial"]) for r in load_runs() if not r.get("failed")}
    todo = [key for key in plan(args.conditions, args.questions, args.trials, args.quiz_trials) if key not in done]
    print(f"[model] {MODEL} / commit {commit} / 実行 {len(todo)} 回（済み {len(done)} 回）", flush=True)
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    for i, (name, qid, trial) in enumerate(todo, 1):
        record = run_once(BY_NAME[name], qid, trial, commit)
        with RUNS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        calls = ", ".join(f"{c['tool']}({c['args']})" for c in record.get("tool_calls", []))
        status = "失敗" if record["failed"] else f"requests={record['requests']} {calls}"
        print(f"  {i}/{len(todo)} {name} {qid} #{trial}: {status}", flush=True)
        if i < len(todo):
            time.sleep(args.interval)


def _calls_text(record: dict) -> str:
    calls = record["tool_calls"]
    if not calls:
        return "（なし）"
    return "<br>".join(f"`{c['tool']}({', '.join(f'{k}={v!r}' for k, v in c['args'].items())})`" for c in calls)


def _ends_with_lecture(output: str) -> bool:
    lines = [line for line in output.strip().splitlines() if line.strip()]
    return bool(lines) and bool(re.search(r"第\s*\d+\s*回", lines[-1]))


def summary() -> None:
    latest = {}
    for r in load_runs():
        if not r.get("failed"):
            latest[(r["condition"], r["question_id"], r["trial"])] = r
    records = sorted(
        latest.values(),
        key=lambda r: (list(QUESTIONS).index(r["question_id"]), list(BY_NAME).index(r["condition"]), r["trial"]),
    )
    print("| 質問 | 条件 | 回 | ツール呼び出し（順） | requests | 入力 / 出力 tokens | 最後の行に第N回 |")
    print("|---|---|---:|---|---:|---:|:---:|")
    for r in records:
        print(
            f"| {r['question_id']} | {r['condition']} | {r['trial']} | {_calls_text(r)} | {r['requests']} "
            f"| {r['input_tokens']:,} / {r['output_tokens']:,} | {'○' if _ends_with_lecture(r['output']) else '－'} |"
        )
    lines = ["# 第3回 宿題（基礎）の実行記録", "", "`scripts/lec03_prompt_variants.py --summary` で runs.jsonl から作った。", ""]
    for r in records:
        lines += [
            f"## {r['question_id']} / {r['condition']} / {r['trial']} 回目",
            "",
            f"- 質問：{r['question']}",
            f"- 変えたこと：{BY_NAME[r['condition']].change}",
            f"- モデル：{r['model_name']}（{r['started_at']}、{r['elapsed_s']} 秒）",
            "",
            "```text",
            r["output"].strip(),
            "",
            r["trace"],
            "```",
            "",
        ]
    (OUT_DIR / "traces.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="第3回 宿題（基礎）: INSTRUCTIONS や docstring を1か所だけ変えて比べる")
    parser.add_argument("--dump", action="store_true", help="条件ごとの指示とツール定義を書き出す（APIキー不要）")
    parser.add_argument("--run", action="store_true", help="LLM に質問して runs.jsonl に追記する（済みの組はとばす）")
    parser.add_argument("--summary", action="store_true", help="表を出し、traces.md を作る")
    parser.add_argument("--conditions", nargs="+", default=list(BY_NAME), choices=list(BY_NAME))
    parser.add_argument("--questions", nargs="+", default=DEFAULT_QUESTIONS, choices=list(QUESTIONS))
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--quiz-trials", type=int, default=3, help="baseline で「確認問題」の質問を何回するか")
    parser.add_argument("--interval", type=float, default=12.0, help="呼び出しの間隔（秒）。無料枠の 15 RPM に収める")
    args = parser.parse_args()
    if not (args.dump or args.run or args.summary):
        parser.error("--dump・--run・--summary のどれかを指定してください")
    if args.dump:
        dump()
    if args.run:
        run(args)
    if args.summary:
        summary()


if __name__ == "__main__":
    main()
