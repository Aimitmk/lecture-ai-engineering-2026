"""第4回 宿題（基礎）: 採点のモデル・rubric.md の文言・判定の順序を 1 つずつ変えて、同じ labels.jsonl で再採点する。

app/judge.py は書き換えない。条件ごとに --model・--rubric を渡すか、出力の型（JudgeResult）と
出力の形式の文を一時的に差し替えて、app.judge.main をそのまま呼ぶ（演習と同じ出力になる）。
差し替えたあとにモデルへ渡る指示と出力の JSON schema は --dump で書き出し、
baseline との違いが意図した所だけであることを確かめる。

使い方（リポジトリの直下で）:
    uv run --frozen python -m scripts.lec04_judge_variants --dump                  # API キー不要
    uv run --frozen --env-file .env python -m scripts.lec04_judge_variants --run   # 各条件 3 回（済んだ run は飛ばす）
    uv run --frozen python -m scripts.lec04_judge_variants --summary               # summary.md（API を呼ばない）
    uv run --frozen python -m scripts.lec04_judge_variants --run --fake --out-dir /tmp/x   # 偽モデルで配線だけ確かめる
"""

import argparse
import contextlib
import copy
import difflib
import io
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import Field, create_model
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.profiles.google import GoogleJsonSchemaTransformer

from app import judge
from app.config import MODEL

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "lectures" / "04" / "results" / "basic"
KEYS = [k for k, _ in judge.ALL_CRITERIA]
LLM_KEYS = [k for k, _ in judge.LLM_CRITERIA]

# app/judge.py の build_judge が rubric の後ろに足す文（--dump で、judge.py と同じ文であることを確かめる）
REASON_FIRST_SUFFIX = (
    "\n\n# 出力の形式\n"
    "4 つの基準（grounding, scope, hint, clarity）それぞれについて、reason（理由）を先に書き、"
    "そのあとで verdict を pass / fail / unsure のどれかにしてください。"
)
VERDICT_FIRST_SUFFIX = (
    "\n\n# 出力の形式\n"
    "4 つの基準（grounding, scope, hint, clarity）それぞれについて、verdict を pass / fail / unsure のどれかに"
    "先に決め、そのあとで reason（理由）を書いてください。"
)
REASON_FIRST_DOC = "1 つの基準に対する判定。reason を先に書かせてから verdict を決めさせる（理由→判定の順）。"
VERDICT_FIRST_DOC = "1 つの基準に対する判定。verdict を先に決めさせてから reason を書かせる（判定→理由の順）。"
REASON_FIRST_RUBRIC = "- 理由は日本語で 1〜2 文。先に理由を書いてから判定を決める\n"
VERDICT_FIRST_RUBRIC = "- 理由は日本語で 1〜2 文。先に判定を決めてから理由を書く\n"

# rubric.md の文言を 1 か所変える条件：演習の採点で、根拠に「宿題の答えを書いた」「役割を変える要求に応じた」
# という他の基準の理由が持ち込まれた（#06・#08）ので、分かりやすさと同じように「この基準で見ること」を書く
GROUNDING_HEAD = "## 根拠（grounding）\n\n"
GROUNDING_ONLY_LINE = (
    "- この基準では、回答に書いた内容が参照と矛盾していないか、ないことを断定していないかだけを見る。"
    "宿題の答えを書いたか（ヒント）や、役割を変える要求に応じたか（範囲）は、ここには持ち込まない\n"
)


def _replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"置き換える文が1か所ではありません: {old!r}")
    return text.replace(old, new)


@dataclass(frozen=True)
class Condition:
    name: str
    change: str  # 何を変えたか
    model: str | None = None  # None なら既定（AIE_MODEL）
    rubric_edit: tuple[str, str] | None = None  # rubric.md の（変更前, 変更後）
    verdict_first: bool = False  # 出力の型で verdict を reason より先にする
    verdict_first_text: bool = False  # 「理由を先に」と書いた文（docstring・出力の形式）も「判定を先に」にする
    wait: float = 5.0  # 1 件ごとに待つ秒数


CONDITIONS = [
    Condition("baseline", "変更なし（STEP 3 の後の rubric.md、gemini-3.5-flash-lite、理由→判定）"),
    # gemini-3.5-flash の無料枠は 1 日 20 回（429 の本文: GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit 20）。
    # 1 回の run で 10 回呼ぶので、1 日に取れるのは 2 回まで。2026-11-15 は、試しの呼び出しも含めて 1 回目しか取れず、
    # 2・3 回目は上限が戻った 17:00 JST より後（20:30）に取った
    Condition("model_flash", "採点のモデルを gemini-3.5-flash にする", model="gemini-3.5-flash", wait=8.0),
    Condition(
        "rubric_grounding",
        "rubric.md の「根拠」の先頭に、内容だけを見て他の基準（ヒント・範囲）の理由を持ち込まない、と 1 行書き足す",
        rubric_edit=(GROUNDING_HEAD, GROUNDING_HEAD + GROUNDING_ONLY_LINE),
    ),
    Condition(
        "order_schema",
        "出力の型（CriterionVerdict）の reason と verdict の順だけを入れ替える（説明文はそのまま）",
        verdict_first=True,
    ),
    Condition(
        "order_all",
        "出力の型の順を入れ替え、「理由を先に」と書いた 3 か所（rubric.md の採点のしかた・出力の形式の文・"
        "CriterionVerdict の docstring）も「判定を先に」にする",
        rubric_edit=(REASON_FIRST_RUBRIC, VERDICT_FIRST_RUBRIC),
        verdict_first=True,
        verdict_first_text=True,
    ),
]
BY_NAME = {c.name: c for c in CONDITIONS}


# ---------------------------------------------------------------- 条件の差し替え
def make_judge_result(verdict_first: bool, doc: str):
    """JudgeResult と同じ名前・説明文で、CriterionVerdict のフィールドの順と docstring だけを変えた型を作る。"""
    fields = judge.CriterionVerdict.model_fields
    reason = (str, Field(description=fields["reason"].description))
    verdict = (judge.Verdict, Field(description=fields["verdict"].description))
    ordered = {"verdict": verdict, "reason": reason} if verdict_first else {"reason": reason, "verdict": verdict}
    criterion = create_model("CriterionVerdict", __doc__=doc, **ordered)
    result_fields = {
        name: (criterion, Field(description=info.description)) for name, info in judge.JudgeResult.model_fields.items()
    }
    return create_model("JudgeResult", **result_fields)


def build_judge_verdict_first(model, rubric: str) -> Agent:
    """app.judge.build_judge と同じで、後ろに足す「出力の形式」の文だけを「判定を先に」にしたもの。"""
    return Agent(model, output_type=judge.JudgeResult, instructions=rubric + VERDICT_FIRST_SUFFIX,
                 model_settings={"temperature": 0.0})


@contextlib.contextmanager
def applied(cond: Condition):
    """条件の型と文を、app.judge に一時的に差し替える（終わったら元に戻す）。"""
    saved = (judge.JudgeResult, judge.build_judge)
    try:
        if cond.verdict_first:
            doc = VERDICT_FIRST_DOC if cond.verdict_first_text else REASON_FIRST_DOC
            judge.JudgeResult = make_judge_result(verdict_first=True, doc=doc)
        if cond.verdict_first_text:
            judge.build_judge = build_judge_verdict_first
        yield
    finally:
        judge.JudgeResult, judge.build_judge = saved


def rubric_text(cond: Condition) -> str:
    text = judge.DEFAULT_RUBRIC.read_text(encoding="utf-8")
    return _replace_once(text, *cond.rubric_edit) if cond.rubric_edit else text


def rubric_path(cond: Condition, out_dir: Path) -> Path | None:
    """rubric.md を変える条件では、変えた版を out_dir に書き出して、そのパスを返す（--rubric に渡す）。"""
    if not cond.rubric_edit:
        return None
    stem = cond.name if cond.name.startswith("rubric_") else f"rubric_{cond.name}"
    path = out_dir / f"{stem}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rubric_text(cond), encoding="utf-8")
    return path


# ---------------------------------------------------------------- --dump
def visible_prompt(cond: Condition) -> str:
    """モデルに渡る指示と出力の JSON schema を、FunctionModel（API を呼ばない）で取り出す。

    schema は Gemini に送る形（GoogleJsonSchemaTransformer を通したもの）にして、キーを並べ替えずに書く。
    """
    captured = {}

    def capture(messages, info):
        captured["instructions"] = info.instructions
        captured["tool"] = info.output_tools[0]
        args = {k: {"reason": "dump", "verdict": "pass"} for k in LLM_KEYS}
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=args)])

    with applied(cond):
        agent = judge.build_judge(FunctionModel(capture, model_name="dump"), rubric_text(cond))
        agent.run_sync("dump")
    if cond.name == "baseline":  # 定数が judge.py の文と同じであること（ずれると差分が 1 か所にならない）
        expected = judge.DEFAULT_RUBRIC.read_text(encoding="utf-8") + REASON_FIRST_SUFFIX
        assert captured["instructions"] == expected, "REASON_FIRST_SUFFIX が app/judge.py の文と違います"
    tool = captured["tool"]
    schema = GoogleJsonSchemaTransformer(copy.deepcopy(tool.parameters_json_schema)).walk()
    return "\n".join([
        f"## model\n{cond.model or MODEL}",
        f"## instructions\n{captured['instructions']}",
        f"## output tool: {tool.name}\n{tool.description or ''}",
        "## parameters（Gemini に送る形。キーの順はそのまま）",
        json.dumps(schema, ensure_ascii=False, indent=2),
        "",
    ])


def dump(out_dir: Path) -> None:
    prompts = out_dir / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    base = visible_prompt(BY_NAME["baseline"])
    for cond in CONDITIONS:
        text = base if cond.name == "baseline" else visible_prompt(cond)
        (prompts / f"{cond.name}.txt").write_text(text, encoding="utf-8")
        if cond.name == "baseline":
            continue
        diff = "".join(difflib.unified_diff(
            base.splitlines(keepends=True), text.splitlines(keepends=True),
            fromfile="baseline.txt", tofile=f"{cond.name}.txt",
        ))
        (prompts / f"{cond.name}.diff").write_text(diff, encoding="utf-8")
        changed = sum(1 for line in diff.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))
        print(f"{cond.name:<18} 変わった行 {changed:>2}  → {prompts.relative_to(ROOT) if prompts.is_relative_to(ROOT) else prompts}/{cond.name}.diff")


# ---------------------------------------------------------------- --run
def describe(result) -> dict:
    """1 件の採点の、返ってきた引数のキーの順・使ったトークン・モデル名。"""
    responses = [m for m in result.all_messages() if isinstance(m, ModelResponse)]
    last = responses[-1]
    call = next((p for p in last.parts if isinstance(p, ToolCallPart)), None)
    args = call.args if call else None
    if isinstance(args, str):
        args = json.loads(args)  # 文字列で返ってきた場合も、書かれた順のまま読む
    top, fields = [], {}
    if isinstance(args, dict):
        top = list(args)
        fields = {k: list(v) if isinstance(v, dict) else None for k, v in args.items()}
    usage = result.usage
    return {
        "model_name": last.model_name,
        "responses": len(responses),
        "top_order": top,
        "field_order": fields,
        "usage": {"requests": usage.requests, "input_tokens": usage.input_tokens,
                  "output_tokens": usage.output_tokens, "details": dict(usage.details or {})},
    }


class _Recorder:
    """judge_cases に渡すエージェントの代わり。run_sync の結果を記録してから返す。"""

    def __init__(self, agent: Agent, rows: list[dict]):
        self.agent, self.rows = agent, rows

    def run_sync(self, prompt, **kwargs):
        result = self.agent.run_sync(prompt, **kwargs)
        self.rows.append(describe(result))
        return result


@contextlib.contextmanager
def verbose_api_errors():
    """API のエラー（429 など）の表示に、返ってきた本文の先頭も付ける（どの上限に当たったかを見るため）。"""
    original = judge.api_error_message

    def verbose(status: int, detail: str = "") -> str:
        return original(status, detail) + (f"\n  [detail] {detail}" if detail and status in (429, 503) else "")

    judge.api_error_message = verbose
    try:
        yield
    finally:
        judge.api_error_message = original


@contextlib.contextmanager
def recording(rows: list[dict]):
    """app.judge.judge_cases をそのまま使い、1 件ごとの記録を rows に足す。"""
    original = judge.judge_cases

    def wrapped(agent, cases, wait=0.0):
        start = len(rows)
        verdicts = original(_Recorder(agent, rows), cases, wait)
        for row, case in zip(rows[start:], cases):
            row["id"] = case["id"]
        return verdicts

    judge.judge_cases = wrapped
    try:
        yield
    finally:
        judge.judge_cases = original


class _Tee(io.TextIOBase):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
            st.flush()
        return len(s)


def run_one(cond: Condition, n: int, out_dir: Path, fake: bool, tries: int = 3) -> bool:
    runs = out_dir / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    out = runs / f"{cond.name}_{n}.json"
    if out.exists():
        print(f"[skip] {out.name} はもうあります")
        return True
    argv = ["--out", str(out), "--wait", str(0 if fake else cond.wait)]
    model = "test" if fake else cond.model
    if model:
        argv += ["--model", model]
    if (path := rubric_path(cond, out_dir)) is not None:
        argv += ["--rubric", str(path)]
    for attempt in range(1, tries + 1):
        rows, buf = [], io.StringIO()
        try:
            with applied(cond), recording(rows), verbose_api_errors(), \
                    contextlib.redirect_stdout(_Tee(sys.__stdout__, buf)):
                print(f"# {cond.name} run {n}（{datetime.now():%Y-%m-%d %H:%M:%S} JST）変更: {cond.change}")
                judge.main(argv)
        except (SystemExit, Exception) as e:  # API のエラーは judge.main が表示して SystemExit(1) にする
            print(f"[retry] {cond.name}_{n} が失敗（{attempt}/{tries} 回目: {e!r}）。60 秒待ってやり直します")
            if attempt < tries:
                time.sleep(60)
            continue
        if out.exists():
            out.with_suffix(".txt").write_text(buf.getvalue(), encoding="utf-8")
            with open(out.with_suffix(".raw.jsonl"), "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            return True
    print(f"[give up] {cond.name}_{n}")
    return False


def run(out_dir: Path, names: list[str], repeats: int, fake: bool, pause: float) -> None:
    # 回ごとに全条件を順に回す（時間帯による混み具合の差が、特定の条件に偏らないように）
    for n in range(1, repeats + 1):
        for name in names:
            ok = run_one(BY_NAME[name], n, out_dir, fake)
            if ok and not fake:
                time.sleep(pause)


# ---------------------------------------------------------------- --summary
def _load_runs(out_dir: Path) -> dict[str, list[dict]]:
    by_cond: dict[str, list[dict]] = {}
    for cond in CONDITIONS:
        for path in sorted((out_dir / "runs").glob(f"{cond.name}_*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            raw_path = path.with_suffix(".raw.jsonl")
            data["raw"] = judge.read_jsonl(raw_path) if raw_path.exists() else []
            data["file"] = path.name
            by_cond.setdefault(cond.name, []).append(data)
    return by_cond


def _majority(values: list[str]) -> str:
    return Counter(values).most_common(1)[0][0]


def summary(out_dir: Path) -> str:
    labels = judge.load_labels(judge.DEFAULT_LABELS)
    by_cond = _load_runs(out_dir)
    names = dict(judge.ALL_CRITERIA)
    lines = [
        "# 第4回 宿題（基礎）: 1 つずつ変えて再採点した結果",
        "",
        f"- ラベル：`lectures/04/labels.jsonl`（Claude のラベル、10 件）。評価セット：`data/eval/lec04_cases.jsonl`",
        "- 一致率は「一致 / 比べた件数」。LLM が unsure にした項目は分母から外れる（演習と同じ）",
        "- この表は `uv run --frozen python -m scripts.lec04_judge_variants --summary` で、runs/ の JSON から作り直せる",
        "",
        "## 条件",
        "",
        "| 条件 | 変えたこと |",
        "|---|---|",
    ]
    lines += [f"| {c.name} | {c.change} |" for c in CONDITIONS]

    lines += ["", "## 基準別の一致率（run ごと）", "",
              "| 条件 | run | " + " | ".join(names[k] for k in KEYS) + " | 要確認 | 総合 | coverage | モデル（応答の記録） |",
              "|---|---|" + "---|" * len(KEYS) + "---|---|---|---|"]
    for cond in CONDITIONS:
        for data in by_cond.get(cond.name, []):
            s = data["summary"]
            per = s["per_criterion"]
            cells = [f"{per[k]['agree']}/{per[k]['compared']}" for k in KEYS]
            models = sorted({r["model_name"] for r in data["raw"]}) or [data["model"]]
            lines.append(f"| {cond.name} | {data['file'].rsplit('_', 1)[-1].removesuffix('.json')} | " + " | ".join(cells)
                         + f" | {len(s['review'])} | {s['overall']['agree']}/{s['overall']['compared']}"
                         + f" | {s['coverage']['covered']}/{s['coverage']['total']} | {', '.join(models)} |")

    fails = "・".join(
        f"{names[k]} " + "".join(f"#{cid}" for cid, lab in labels.items() if lab.get(k) == "fail") for k in LLM_KEYS
    )
    lines += ["", "## 合計（全 run）と、不合格の再現率", "",
              "不合格の再現率：ラベルが fail の項目のうち、LLM も fail にした割合（unsure は除く）。"
              f"ラベルが fail の項目は {fails} だけなので、分母は小さい（各 run で 1 件ずつ）。",
              "",
              "| 条件 | run 数 | " + " | ".join(names[k] for k in LLM_KEYS) + " | 要確認（計） | 不合格の再現率（根拠 / 範囲 / ヒント / 分かりやすさ） | 過検出（計） |",
              "|---|---|" + "---|" * len(LLM_KEYS) + "---|---|---|"]
    for cond in CONDITIONS:
        runs = by_cond.get(cond.name, [])
        if not runs:
            continue
        agree = {k: sum(d["summary"]["per_criterion"][k]["agree"] for d in runs) for k in LLM_KEYS}
        compared = {k: sum(d["summary"]["per_criterion"][k]["compared"] for d in runs) for k in LLM_KEYS}
        review = sum(len(d["summary"]["review"]) for d in runs)
        recall = []
        for k in LLM_KEYS:
            hit = tot = 0
            for d in runs:
                for cid, lab in labels.items():
                    j = d["verdicts"].get(cid, {}).get(k, {}).get("verdict")
                    if lab.get(k) == "fail" and j in ("pass", "fail"):
                        tot += 1
                        hit += int(j == "fail")
            recall.append(f"{hit}/{tot}")
        over = sum(1 for d in runs for m in d["summary"]["mismatches"] if m["kind"] == "過検出")
        lines.append(f"| {cond.name} | {len(runs)} | " + " | ".join(f"{agree[k]}/{compared[k]}" for k in LLM_KEYS)
                     + f" | {review} | {' / '.join(recall)} | {over} |")

    lines += ["", "## 不一致と要確認の中身（全 run）", ""]
    for cond in CONDITIONS:
        items = Counter()
        for d in by_cond.get(cond.name, []):
            for m in d["summary"]["mismatches"]:
                items[f"#{m['id']} {m['name']} {m['kind']}（LLM={m['judge']}）"] += 1
            for r in d["summary"]["review"]:
                items[f"#{r['id']} {r['name']} 要確認"] += 1
        n = len(by_cond.get(cond.name, []))
        body = "、".join(f"{k} ×{v}/{n}" for k, v in sorted(items.items())) or "なし"
        lines.append(f"- **{cond.name}**：{body}")

    base_runs = by_cond.get("baseline", [])
    if base_runs:
        lines += ["", "## baseline（多数決）から判定が変わった項目", "",
                  "baseline の 3 回の多数決と比べ、各条件で判定が違った回数（「×回数/run 数」）。", ""]
        base = {cid: {k: _majority([d["verdicts"][cid][k]["verdict"] for d in base_runs]) for k in LLM_KEYS}
                for cid in labels}
        for cond in CONDITIONS:
            flips = Counter()
            for d in by_cond.get(cond.name, []):
                for cid in labels:
                    for k in LLM_KEYS:
                        v = d["verdicts"][cid][k]["verdict"]
                        if v != base[cid][k]:
                            flips[f"#{cid} {names[k]} {base[cid][k]}→{v}"] += 1
            n = len(by_cond.get(cond.name, []))
            body = "、".join(f"{k} ×{v}/{n}" for k, v in sorted(flips.items())) or "なし"
            lines.append(f"- **{cond.name}**：{body}")

    lines += ["", "## 返ってきた引数の順と、使ったトークン（1 件あたりの平均）", "",
              "「理由が先」：各基準の引数で reason が verdict より先に書かれていた割合（4 基準 × 10 件 × run 数）。"
              "上位のキーの順は、schema の順（根拠・範囲・ヒント・分かりやすさ）どおりだった件数。",
              "",
              "| 条件 | 理由が先 | 判定が先 | 上位のキーが schema の順 | 入力 tokens | 出力 tokens | thoughts tokens | 応答の数 |",
              "|---|---|---|---|---|---|---|---|"]
    for cond in CONDITIONS:
        raws = [r for d in by_cond.get(cond.name, []) for r in d["raw"]]
        if not raws:
            continue
        orders = [tuple(r["field_order"].get(k) or ()) for r in raws for k in LLM_KEYS]
        rf = sum(1 for o in orders if o[:2] == ("reason", "verdict"))
        vf = sum(1 for o in orders if o[:2] == ("verdict", "reason"))
        top_ok = sum(1 for r in raws if r["top_order"] == LLM_KEYS)

        def mean(key):
            return sum(r["usage"][key] for r in raws) / len(raws)

        thoughts = sum(r["usage"]["details"].get("thoughts_tokens", 0) for r in raws) / len(raws)
        responses = sum(r["responses"] for r in raws) / len(raws)
        lines.append(f"| {cond.name} | {rf}/{len(orders)} | {vf}/{len(orders)} | {top_ok}/{len(raws)} | "
                     f"{mean('input_tokens'):.0f} | {mean('output_tokens'):.0f} | {thoughts:.0f} | {responses:.2f} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dump", action="store_true", help="各条件の指示と出力の schema を書き出す（API キー不要）")
    parser.add_argument("--run", action="store_true", help="各条件を --repeats 回ずつ採点する")
    parser.add_argument("--summary", action="store_true", help="runs/ の結果から summary.md を作る")
    parser.add_argument("--conditions", nargs="*", default=[c.name for c in CONDITIONS], choices=list(BY_NAME))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--pause", type=float, default=10.0, help="run と run の間に待つ秒数")
    parser.add_argument("--fake", action="store_true", help="API を呼ばない偽モデル（--model test）で配線だけ確かめる")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    if not (args.dump or args.run or args.summary):
        parser.error("--dump / --run / --summary のどれかを指定してください")
    if args.dump:
        dump(args.out_dir)
    if args.run:
        run(args.out_dir, args.conditions, args.repeats, args.fake, args.pause)
    if args.summary:
        text = summary(args.out_dir)
        (args.out_dir / "summary.md").write_text(text, encoding="utf-8")
        print(text)


if __name__ == "__main__":
    main()
