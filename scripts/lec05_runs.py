"""第5回: 同じ質問を、取得方法や設定を 1 つずつ変えて --trace 付きで実行し、記録する。

app/ の既定の動きは変えない。1 回の実行ごとに子プロセスを起動し、条件を差し替えてから
app.agent.main() を --trace 付きで呼ぶ（画面の表示は CLI の --trace と同じ）。
標準の --trace は tool return を 120 文字で切るので、どのページの本文をモデルに渡したかは、
print_trace を包んで受け取った result から取り出し、同じ名前の .json に残す。
ページ本文と、全文投入の入力は保存しない（page_id から lectures.json で引ける）。

使い方（リポジトリの直下で）:
    uv run --frozen --env-file .env python -m scripts.lec05_runs run                  # 本番。済んだ実行は飛ばす
    uv run --frozen --env-file .env python -m scripts.lec05_runs pilot vector memory  # 1 回だけ（表には使わない）
    uv run --frozen python -m scripts.lec05_runs citations                            # 引用の読み取りを手で確かめる
    uv run --frozen python -m scripts.lec05_runs blind                                # 条件名を伏せた判定用ファイル
    uv run --frozen python -m scripts.lec05_runs summary                              # 表を作り直す（API なし）
"""

import argparse
import json
import random
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEC = ROOT / "lectures" / "05"
RESULTS = LEC / "results"
RUNS_DIR = RESULTS / "runs"
PILOT_DIR = RESULTS / "probe" / "pilot"
JUDGE_DIR = RESULTS / "judge"
QUESTIONS = LEC / "questions.json"
SOURCE = ROOT / "data" / "rag_data" / "lectures.json"
JST = timezone(timedelta(hours=9))

REPEATS = 3
PAUSE_SECONDS = 5
PAUSE_AFTER_FULL_CONTEXT = 60  # 全文投入は 1 回で入力が大きいので、長めにあける
# やり直すときは、1 回分を最初から流し直す（記録に残る時間に、待ち時間を混ぜないため）。
# 2026-11-18 の夜は 503（high demand）が試行の約半分で出たので、3 回・60 秒から、6 回・段々長く待つ形に変えた。
RETRY_WAITS = (30, 60, 120, 180, 240)
TRIES = len(RETRY_WAITS) + 1
# tools.py が API エラーを、この文の error としてモデルに返す（モデルのせいではないので、やり直す）
API_ERROR = re.compile(r"レート制限|混み合って|APIキーかモデル名|APIエラー|検索DBがありません")
SEARCH_TOOLS = ("search_materials", "search_outline")


@dataclass(frozen=True)
class Condition:
    name: str
    label: str
    args: tuple[str, ...] = ()
    top_k: int | None = None  # 基礎: app.retrieval.RAG_TOP_K を差し替える（None は既定の 5）


CONDITIONS = {c.name: c for c in [
    Condition("vector", "ベクトル検索 K=5（既定）"),
    Condition("full", "全文投入", ("--full-context",)),
    Condition("tree", "Tree", ("--tree",)),
    Condition("graph", "Graph", ("--graph",)),
    Condition("k3", "ベクトル検索 K=3", top_k=3),
    Condition("k10", "ベクトル検索 K=10", top_k=10),
    Condition("neighbors", "K=5＋前後1ページ", ("--neighbors",)),
    Condition("outline", "検索＋目次", ("--outline",)),
]}
EXPECTED_HITS = {"vector": 5, "k3": 3, "k10": 10, "neighbors": 5, "outline": 5}

# レベルごとに比べる条件。vector（K=5）は全レベル共通の基準で、同じ実行を使い回す。
LEVELS = {
    "exercise": ("演習", ("full", "vector", "tree", "graph")),
    "basic": ("基礎", ("vector", "k3", "k10")),
    "impl": ("実装", ("vector", "neighbors")),
    "advanced": ("発展", ("vector", "outline")),
}
EXERCISE_QUESTIONS = ("lora", "memory", "none")
EXERCISE_ONLY = ("full", "tree", "graph")  # 演習の 3 問だけで回す


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["questions"]


def planned(questions: list[dict]) -> list[tuple[str, str]]:
    """（条件, 質問）の組。質問ごとに、条件を決まった順に並べる（1 回の中で条件が交互になる）。"""
    pairs = []
    for q in questions:
        for name in CONDITIONS:
            if name in EXERCISE_ONLY and q["id"] not in EXERCISE_QUESTIONS:
                continue
            pairs.append((name, q["id"]))
    return pairs


# ---------------------------------------------------------------- 子プロセス（1 回の実行）

def summarize_return(tool: str, content) -> dict:
    """tool return から、モデルに本文を渡したページ（given）と、見出しだけ見せたページを取り出す。"""
    out = {"tool": tool, "pages": []}
    try:
        data = json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        out["error"] = f"JSON でない戻り値: {str(content)[:200]}"
        return out
    if not isinstance(data, dict):
        return out
    if data.get("error"):
        out["error"] = data["error"]

    def add(page_id: str, role: str, given: bool, **extra) -> None:
        out["pages"].append({"page_id": page_id, "role": role, "given": given, **extra})

    if tool == "search_materials":
        for hit in data.get("results", []):
            if "neighbor_of" in hit:
                add(hit["page_id"], "neighbor", True, neighbor_of=hit["neighbor_of"])
            else:
                add(hit["page_id"], "hit", True, distance=round(hit["distance"], 4))
        out["n_hits"] = sum(1 for p in out["pages"] if p["role"] == "hit")
    elif tool == "search_graph":
        for key, role in (("seeds", "seed"), ("expanded", "expanded")):
            for page in data.get(key, []):
                route = [node["id"] for node in page.get("path", [])]
                add(page["page_id"], role, True, hops=page.get("hops"),
                    via_term=any(node.startswith("term:") for node in route), path=route)
    elif tool == "browse_tree":
        node = data.get("node") or {}
        out["node"] = node.get("id")
        if node.get("kind") == "page":
            add(node["id"], "node", True)
        out["children"] = [child["id"] for child in data.get("children", [])]
    elif tool == "search_outline":
        for hit in data.get("results", []):
            add(hit["page_id"], "hit", True, distance=round(hit["distance"], 4))
        out["n_hits"] = len(data.get("results", []))
        # 目次は「p.13 見出し［lec03-main-p013］」の行。見出しだけを見せたページ（本文は渡していない）
        out["outline_pages"] = re.findall(r"［([^］]+)］", json.dumps(data.get("outline", []), ensure_ascii=False))
    elif tool == "read_pages":
        for page in data.get("pages", []):
            add(page["page_id"], "read", True)
        out["not_found"] = data.get("not_found", [])
        out["skipped"] = data.get("skipped", [])
    return out


def describe(result, elapsed: float) -> dict:
    from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart

    calls, returns, models = [], [], []
    for message in result.all_messages():
        if isinstance(message, ModelResponse) and message.model_name:
            models.append(message.model_name)
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                calls.append({"tool": part.tool_name, "args": part.args_as_dict()})
            elif isinstance(part, ToolReturnPart):
                returns.append(summarize_return(part.tool_name, part.content))
    given = []
    for ret in returns:
        for page in ret["pages"]:
            if page["given"] and page["page_id"] not in given:
                given.append(page["page_id"])
    usage = result.usage
    return {
        "elapsed_seconds": round(elapsed, 2),
        "response_models": sorted(set(models)),
        "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                  "requests": usage.requests, "tool_calls": usage.tool_calls},
        # 「算定不可」を 0 として扱わないよう、文字列のまま持つ
        "cost": f"${usage.cost:.6f}" if usage.cost is not None else "算定不可",
        "tool_calls": calls,
        "tool_returns": returns,
        "pages_given": given,
        "errors": [ret["error"] for ret in returns if ret.get("error")],
        "output": result.output if isinstance(result.output, str) else repr(result.output),
    }


def child(cond_name: str, question: str, sidecar: Path) -> None:
    cond = CONDITIONS[cond_name]
    from app import retrieval

    if cond.top_k is not None:
        # retrieval は `from app.config import RAG_TOP_K` で値を持つので、app.config ではなくこちらを変える
        retrieval.RAG_TOP_K = cond.top_k
    original_embed = retrieval.embed_text

    def embed_logged(text, task_type):
        try:
            return original_embed(text, task_type)
        except Exception as e:  # tools.py はエラーの種類だけをモデルに返すので、本文をここで残す
            print(f"[embed error] {type(e).__name__}: {str(e)[:800]}", file=sys.stderr, flush=True)
            raise

    retrieval.embed_text = embed_logged

    import app.agent as agent_module

    original_message = agent_module.api_error_message

    def verbose_message(status: int, detail: str = "") -> str:
        text = original_message(status, detail)
        return text + (f"\n  [detail] {detail}" if detail and status in (429, 503) else "")

    agent_module.api_error_message = verbose_message
    captured = {}
    original_trace = agent_module.print_trace

    def capture(result, elapsed_seconds=None):
        captured.update(result=result, elapsed=elapsed_seconds)
        original_trace(result, elapsed_seconds)

    agent_module.print_trace = capture

    # 失敗したときの記録（2026-11-19 03:50 に足した。成功した実行の動きは変えない）。
    # app/agent.py は API エラーの本文を 200 文字で切るので、どの上限に当たったか（quotaId）が残らない。
    # 全文と、失敗するまでに何回応答し、どのツールを呼んだかを stderr に残す。
    from pydantic_ai import capture_run_messages
    from pydantic_ai.exceptions import ModelHTTPError
    from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart

    inner_run_sync = agent_module.agent.run_sync

    def run_sync_logged(*args, **kwargs):
        try:
            return inner_run_sync(*args, **kwargs)
        except ModelHTTPError as e:
            print(f"[http error] {e.status_code} {e.body}", file=sys.stderr, flush=True)
            raise

    agent_module.agent.run_sync = run_sync_logged
    sys.argv = ["app.agent", "--trace", *cond.args, question]
    started = datetime.now(JST)
    with capture_run_messages() as messages:
        try:
            agent_module.main()
        except SystemExit:
            responses = sum(isinstance(m, ModelResponse) for m in messages)
            print(f"[partial] 失敗するまでの応答 {responses} 回", file=sys.stderr)
            for m in messages:
                for part in m.parts:
                    if isinstance(part, ToolCallPart):
                        print(f"[partial] call {part.tool_name} {json.dumps(part.args_as_dict(), ensure_ascii=False)}",
                              file=sys.stderr)
                    elif isinstance(part, ToolReturnPart):
                        ret = summarize_return(part.tool_name, part.content)
                        print(f"[partial] return {part.tool_name} {[p['page_id'] for p in ret['pages']]}"
                              + (f" error={ret['error']}" if ret.get("error") else ""), file=sys.stderr)
            sys.stderr.flush()
            raise
    sys.stdout.flush()
    record = describe(captured["result"], captured["elapsed"])
    record.update(condition=cond.name, args=list(cond.args), rag_top_k=retrieval.RAG_TOP_K,
                  full_context="--full-context" in cond.args, model=agent_module.MODEL,
                  question=question, started_at=started.isoformat(timespec="seconds"))
    sidecar.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 親プロセス（実行の管理）

def run_one(cond: Condition, q: dict, rep: int, out_dir: Path) -> str:
    """1 回分を実行して保存する。戻り値は ok・skip・failed。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"{cond.name}__{q['id']}__{rep}"
    sidecar = stem.with_suffix(".json")
    if sidecar.exists():
        return "skip"
    tmp = stem.with_suffix(".tmp.json")
    for attempt in range(1, TRIES + 1):
        tmp.unlink(missing_ok=True)
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.lec05_runs", "child", cond.name,
             "--question", q["question"], "--sidecar", str(tmp)],
            cwd=ROOT, capture_output=True, text=True, timeout=900)
        problems = [] if proc.returncode == 0 else [f"終了コード {proc.returncode}"]
        record = json.loads(tmp.read_text(encoding="utf-8")) if tmp.exists() else None
        if record is None:
            problems.append("記録なし")
        else:
            problems += [f"API のエラー: {e}" for e in record["errors"] if API_ERROR.search(e)]
            expected = EXPECTED_HITS.get(cond.name)
            wrong = [r.get("n_hits") for r in record["tool_returns"]
                     if r["tool"] in SEARCH_TOOLS and not r.get("error") and r.get("n_hits") != expected]
            if expected is not None and wrong:
                raise SystemExit(f"[stop] 検索の件数が K={expected} と合わない: {wrong}（{stem.name}）")
        if not problems:
            record.update(question_id=q["id"], rep=rep, attempt=attempt)
            stem.with_suffix(".txt").write_text(proc.stdout, encoding="utf-8")
            if proc.stderr.strip():
                stem.with_suffix(".err.txt").write_text(proc.stderr, encoding="utf-8")
            sidecar.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.unlink(missing_ok=True)
            return "ok"
        failed = stem.parent / f"{stem.name}.fail{attempt}.txt"
        failed.write_text(f"# {datetime.now(JST).isoformat(timespec='seconds')} {'; '.join(problems)}\n\n"
                          f"[stdout]\n{proc.stdout}\n[stderr]\n{proc.stderr[-6000:]}", encoding="utf-8")
        print(f"[retry] {stem.name}: {'; '.join(problems)}（{attempt}/{TRIES} 回目）", flush=True)
        if attempt < TRIES:
            time.sleep(RETRY_WAITS[attempt - 1])
    tmp.unlink(missing_ok=True)
    return "failed"


def brief(path: Path) -> str:
    r = json.loads(path.read_text(encoding="utf-8"))
    u = r["usage"]
    return (f"{r['elapsed_seconds']}秒・入力{u['input_tokens']:,}/出力{u['output_tokens']:,}・"
            f"応答{u['requests']}回・{r['cost']}・ツール{len(r['tool_calls'])}回")


def run(questions: list[dict], only: set[str] | None, repeats: int) -> None:
    by_id = {q["id"]: q for q in questions}
    failures_in_row = 0
    for rep in range(1, repeats + 1):  # 幅優先：全条件の 1 回目 → 2 回目 → 3 回目
        for cond_name, qid in planned(questions):
            if only and cond_name not in only:
                continue
            status = run_one(CONDITIONS[cond_name], by_id[qid], rep, RUNS_DIR)
            if status == "skip":
                continue
            stem = RUNS_DIR / f"{cond_name}__{qid}__{rep}"
            now = datetime.now(JST).strftime("%H:%M:%S")
            print(f"[{now}] [{status}] {stem.name}"
                  + (f"  {brief(stem.with_suffix('.json'))}" if status == "ok" else ""), flush=True)
            failures_in_row = failures_in_row + 1 if status == "failed" else 0
            if failures_in_row >= 2:
                raise SystemExit("[stop] 2 回続けて失敗した。上限に当たった可能性がある。"
                                 "fail*.txt の本文を確かめてから再開する（済んだ実行は飛ばされる）")
            time.sleep(PAUSE_AFTER_FULL_CONTEXT if cond_name == "full" else PAUSE_SECONDS)


# ---------------------------------------------------------------- 引用の読み取り

def _documents() -> tuple[dict, set[str]]:
    docs = json.loads(SOURCE.read_text(encoding="utf-8"))
    titles = {unicodedata.normalize("NFKC", d["title"]): d["id"] for d in docs}
    page_ids = {p["id"] for d in docs for s in d["content"] for p in s["content"]}
    return titles, page_ids


TITLES, ALL_PAGE_IDS = _documents()
_NUM = r"\d{1,3}"
_RANGE = rf"{_NUM}(?:\s*[-–—~〜]\s*{_NUM})?"
_SEP = r"\s*(?:,|、|，|・|/|及び|および|と)\s*"
PAGE_GROUP = re.compile(rf"(?<![A-Za-z])[pP]{{1,2}}\.\s*({_RANGE}(?:{_SEP}(?:[pP]{{1,2}}\.\s*)?{_RANGE})*)")
LECTURE = re.compile(r"第\s*(\d{1,2})\s*回(\s*(?:の)?\s*(?:演習|宿題))?")
DOC_ID = re.compile(r"(?<![A-Za-z0-9])(lec\d{2}-(?:main|exercise)|orientation)(?![A-Za-z0-9-])")
MULTI_LECTURE = re.compile(r"第\s*\d{1,2}\s*[・、,]\s*\d{1,2}\s*回")  # 「第1・2回」：どのページがどの回か決まらない

# 読み取りで資料が決まらず、手で読んだもの（実行の名前 → その箇所の引用と理由）。
MANUAL_CITATIONS = {
    "vector__publish_ok__2": {
        "text": "第1・2回・PDF p.17, 40-42",
        "pages": ["lec02-main-p017", "lec01-main-p040", "lec01-main-p041", "lec01-main-p042"],
        "reason": "同じ回答が 9 行目で「第2回・PDF p.17」と書いている。第2回 p.17 は「クイズ 1：公開してよい？（答え）」、"
                  "第1回 p.40〜42 は評価の問題設定で、第1回 p.17・第2回 p.40〜42 は質問と関係が無い",
    },
}


def _expand(group: str) -> list[int]:
    pages = []
    for part in re.split(_SEP, group):
        part = re.sub(r"^[pP]{1,2}\.\s*", "", part.strip())
        if not part:
            continue
        bounds = re.split(r"\s*[-–—~〜]\s*", part)
        if len(bounds) == 2 and bounds[0].isdigit() and bounds[1].isdigit():
            a, b = int(bounds[0]), int(bounds[1])
            pages += list(range(a, b + 1)) if 0 < b - a <= 10 else [a, b]
        elif part.isdigit():
            pages.append(int(part))
    return pages


def parse_citations(text: str) -> list[dict]:
    """回答の「第N回・PDF p.N」などを (資料ID, ページ) にする。資料が読めないものは doc=None。

    資料は、同じ行の直前（無ければ直後）にある「第N回」・資料ID・資料名から決める（how="line"）。
    同じ行に無いときは、それより前の行で最後に出た資料とみなす（how="inferred"。全文投入の回答が
    「資料: lec02-main / …」の行の下に「PDFページ番号: p.51、p.52」と書く形）。
    ただし「第1・2回」のように回が 2 つ並ぶ行は決めない（doc=None、how="multi"。MANUAL_CITATIONS で手で読む）。
    「第N回」は本講義（lecNN-main）、「第N回の演習」は演習資料（lecNN-exercise）とみなす。
    """
    t = unicodedata.normalize("NFKC", text)
    anchors = [(m.start(), f"lec{int(m.group(1)):02d}-{'exercise' if m.group(2) else 'main'}")
               for m in LECTURE.finditer(t)]
    anchors += [(m.start(), m.group(1)) for m in DOC_ID.finditer(t)]
    for title, doc_id in TITLES.items():
        anchors += [(m.start(), doc_id) for m in re.finditer(re.escape(title), t)]
    anchors.sort()
    cites = []
    for m in PAGE_GROUP.finditer(t):
        line_start = t.rfind("\n", 0, m.start()) + 1
        line_end = t.find("\n", m.end())
        line_end = len(t) if line_end < 0 else line_end
        before = [doc for pos, doc in anchors if line_start <= pos < m.start()]
        after = [doc for pos, doc in anchors if m.end() <= pos < line_end]
        doc = before[-1] if before else (after[0] if after else None)
        how = "line"
        if doc is None:
            earlier = [d for pos, d in anchors if pos < line_start]
            if MULTI_LECTURE.search(t[line_start:line_end]):
                how = "multi"
            elif earlier:
                doc, how = earlier[-1], "inferred"
        for page in _expand(m.group(1)):
            if not any(c["doc"] == doc and c["page"] == page for c in cites):
                cites.append({"doc": doc, "page": page, "how": how})
    return cites


def page_id_of(cite: dict) -> str | None:
    if cite["doc"] is None:
        return None
    page_id = f"{cite['doc']}-p{cite['page']:03d}"
    return page_id if page_id in ALL_PAGE_IDS else f"{page_id}（存在しない）"


# ---------------------------------------------------------------- 集計

def label(page_id: str) -> str:
    doc, page = page_id.rsplit("-p", 1)
    if doc.endswith("-main") and doc.startswith("lec"):
        return f"第{int(doc[3:5])}回p.{int(page)}"
    return f"{doc} p.{int(page)}"


def load_runs(directory: Path = RUNS_DIR) -> list[dict]:
    runs = []
    for path in sorted(directory.glob("*__*__*.json")):
        if path.name.endswith(".tmp.json"):
            continue
        r = json.loads(path.read_text(encoding="utf-8"))
        r["stem"] = path.stem
        runs.append(r)
    return runs


def measure(run: dict, gold: list[str]) -> dict:
    cites = parse_citations(run["output"])
    cited = [page_id_of(c) for c in cites]
    manual = MANUAL_CITATIONS.get(run["stem"])
    unresolved = [c["page"] for c in cites if c["doc"] is None]
    if manual:  # 手で読んだ分を足し、決まらなかったページは残さない
        cited += [p for p in manual["pages"] if p not in cited]
        unresolved = []
    given = set(ALL_PAGE_IDS) if run["full_context"] else set(run["pages_given"])
    return {
        "gold_given": {g: g in given for g in gold},
        "gold_cited": {g: g in cited for g in gold},
        "cited": [c for c in cited if c],
        "inferred": [page_id_of(c) for c in cites if c["how"] == "inferred"],
        "manual": manual["pages"] if manual else [],
        "unresolved": unresolved,
        "cited_not_given": [] if run["full_context"] else [c for c in cited if c and c not in given],
        "n_given": len(given) if not run["full_context"] else None,
    }


def load_judgments() -> dict[str, dict]:
    """判定（blind ID ごと）を、実行の名前（stem）ごとに引けるようにする。"""
    key_path, judged_path = JUDGE_DIR / "blind_key.json", JUDGE_DIR / "judgments.jsonl"
    if not (key_path.exists() and judged_path.exists()):
        return {}
    key = json.loads(key_path.read_text(encoding="utf-8"))
    judged = {}
    for line in judged_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            j = json.loads(line)
            judged[key[j["id"]]] = j
    return judged


def _join(values) -> str:
    return "・".join(str(v) for v in values)


def _counts(per_run: list[dict], gold: list[str], key: str) -> str:
    return "・".join(f"{label(g)} {sum(m[key][g] for m in per_run)}/{len(per_run)}" for g in gold) or "－"


def level_table(level: str, runs: list[dict], questions: list[dict], judged: dict) -> list[str]:
    title, cond_names = LEVELS[level]
    lines = []
    for q in questions:
        if level == "exercise" and q["id"] not in EXERCISE_QUESTIONS:
            continue
        lines += ["", f"### {q['id']}（{q['kind']}）", "", f"質問：{q['question']}", "",
                  f"根拠ページ：{'・'.join(label(g) for g in q['gold']) or 'なし（資料にない）'}", "",
                  "| 条件 | 判定（Claude） | 根拠の本文を渡せた | 根拠を引用 | 渡していないページの引用 | 本文を渡したページ数 "
                  "| 時間（秒） | 入力 tokens | 出力 tokens | 応答回数 | 推定費用（USD） | ツール呼び出し |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for name in cond_names:
            mine = sorted((r for r in runs if r["condition"] == name and r["question_id"] == q["id"]),
                          key=lambda r: r["rep"])
            if not mine:
                lines.append(f"| {CONDITIONS[name].label} | 未実行 |" + " |" * 10)
                continue
            per_run = [measure(r, q["gold"]) for r in mine]
            verdicts = [judged.get(r["stem"], {}).get("verdict", "未") for r in mine]
            not_given = [_join(label(p) if "（" not in p else p for p in m["cited_not_given"]) or "なし"
                         for m in per_run]
            calls = [len(r["tool_calls"]) for r in mine]
            inputs = [format(r["usage"]["input_tokens"], ",") for r in mine]
            n_given = [m["n_given"] if m["n_given"] is not None else "全" for m in per_run]
            lines.append(
                f"| {CONDITIONS[name].label} | {_join(verdicts)} | {_counts(per_run, q['gold'], 'gold_given')} "
                f"| {_counts(per_run, q['gold'], 'gold_cited')} | {' / '.join(not_given)} "
                f"| {_join(n_given)} | {_join(r['elapsed_seconds'] for r in mine)} | {_join(inputs)} "
                f"| {_join(r['usage']['output_tokens'] for r in mine)} "
                f"| {_join(r['usage']['requests'] for r in mine)} "
                f"| {_join(r['cost'].lstrip('$') for r in mine)} | {_join(calls)} |")
    return lines


def run_details(runs: list[dict], questions: list[dict], cond_names) -> list[str]:
    """実行ごとの、ツールの呼び方（引数）と、本文を渡したページ・引用したページ。"""
    gold_of = {q["id"]: q["gold"] for q in questions}
    lines = []
    for r in sorted(runs, key=lambda r: (r["question_id"], list(CONDITIONS).index(r["condition"]), r["rep"])):
        if r["condition"] not in cond_names:
            continue
        m = measure(r, gold_of[r["question_id"]])
        calls = "、".join(f"{c['tool']}({json.dumps(c['args'], ensure_ascii=False)})" for c in r["tool_calls"]) or "なし"
        given = "全資料" if r["full_context"] else "・".join(label(p) for p in r["pages_given"]) or "なし"
        lines += [f"- `{r['stem']}`（{r['started_at']}）",
                  f"  - ツール：{calls}",
                  f"  - 本文を渡したページ：{given}",
                  f"  - 引用：{'・'.join(label(p) if '（' not in p else p for p in m['cited']) or 'なし'}"
                  + (f"（資料が読めない p.{_join(m['unresolved'])}）" if m["unresolved"] else "")]
    return lines


def graph_paths(runs: list[dict]) -> list[str]:
    lines = ["| 実行 | expanded の数 | 前後ページ経由 | 用語経由 | 用語経由のページ |", "|---|---|---|---|---|"]
    for r in runs:
        if r["condition"] != "graph":
            continue
        expanded = [p for ret in r["tool_returns"] if ret["tool"] == "search_graph"
                    for p in ret["pages"] if p["role"] == "expanded"]
        via_term = [p for p in expanded if p["via_term"]]
        lines.append(f"| `{r['stem']}` | {len(expanded)} | {len(expanded) - len(via_term)} | {len(via_term)} | "
                     f"{'・'.join(label(p['page_id']) for p in via_term) or 'なし'} |")
    return lines


def summary() -> None:
    questions = load_questions()
    runs = load_runs()
    judged = load_judgments()
    for level, (title, cond_names) in LEVELS.items():
        out = RESULTS / level / "summary.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"# 第5回 {title}：結果の表（`scripts/lec05_runs.py summary` が保存した記録から作る。API は呼ばない）", "",
                 f"- 比べた条件：{'・'.join(CONDITIONS[n].label for n in cond_names)}。各 3 回。値は 1・2・3 回目の順。",
                 "- 根拠の本文を渡せた／根拠を引用：根拠ページごとに、3 回のうち何回か。",
                 "- 渡していないページの引用：本文をモデルに渡していないページを、回答が引用した回（全文投入は対象外）。",
                 "- 判定（Claude）：questions.json の要点に照らした Claude の判定（条件名を伏せて判定した。results/judge/）。",
                 "- 推定費用：`[cost]` の値（生成 API のみ。埋め込みと索引構築は含まない）。"]
        lines += level_table(level, runs, questions, judged)
        if level == "exercise":
            lines += ["", "## Graph の expanded の経路", ""] + graph_paths(runs)
        lines += ["", "## 実行ごとの記録", ""] + run_details(runs, questions, cond_names)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"[summary] {out.relative_to(ROOT)}")


# ---------------------------------------------------------------- 判定用

def blind(seed: int = 5) -> None:
    """条件名を伏せ、順番を混ぜた判定用ファイルを作る（判定するまで blind_key.json は開かない）。"""
    questions = {q["id"]: q for q in load_questions()}
    runs = load_runs()
    random.Random(seed).shuffle(runs)
    key, lines = {}, ["# 第5回 判定用（条件名を伏せ、順番を混ぜた）", "",
                      "要点ごとに ○（合う）・△（一部）・×（無い・誤り）を付け、judgments.jsonl に書く。", ""]
    for i, r in enumerate(sorted(runs, key=lambda r: list(questions).index(r["question_id"])), 1):
        bid = f"B{i:03d}"
        key[bid] = r["stem"]
        q = questions[r["question_id"]]
        lines += [f"## {bid}（{q['id']}）", "", f"質問：{q['question']}", "",
                  "要点：" + " / ".join(f"{p['id']}={p['text']}" for p in q.get("points", [])), "",
                  "```text", r["output"].strip(), "```", ""]
    JUDGE_DIR.mkdir(parents=True, exist_ok=True)
    (JUDGE_DIR / "blind.md").write_text("\n".join(lines), encoding="utf-8")
    (JUDGE_DIR / "blind_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[blind] {len(key)} 件 → {(JUDGE_DIR / 'blind.md').relative_to(ROOT)}")


def citations(n: int, seed: int = 1) -> None:
    """引用の読み取りを手で確かめるため、回答と読み取った結果を並べる。"""
    runs = load_runs()
    random.Random(seed).shuffle(runs)
    for r in runs[:n]:
        print(f"===== {r['stem']}\n{r['output'].strip()}\n--- 読み取り: "
              f"{[page_id_of(c) or ('?', c['page']) for c in parse_citations(r['output'])]}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="本番（各条件 3 回、幅優先。済んだ実行は飛ばす）")
    p_run.add_argument("--only", nargs="*", help="この条件だけ回す")
    p_run.add_argument("--repeats", type=int, default=REPEATS)
    p_pilot = sub.add_parser("pilot", help="1 回だけ実行する（results/probe/pilot/。表には使わない）")
    p_pilot.add_argument("condition", choices=list(CONDITIONS))
    p_pilot.add_argument("question_id")
    p_child = sub.add_parser("child", help="（内部用）1 回分を実行する")
    p_child.add_argument("condition", choices=list(CONDITIONS))
    p_child.add_argument("--question", required=True)
    p_child.add_argument("--sidecar", type=Path, required=True)
    p_cite = sub.add_parser("citations", help="引用の読み取りを、回答と並べて表示する")
    p_cite.add_argument("-n", type=int, default=10)
    sub.add_parser("blind", help="条件名を伏せた判定用ファイルを作る")
    sub.add_parser("summary", help="保存した記録から表を作り直す（API なし）")
    args = parser.parse_args()

    if args.command == "child":
        child(args.condition, args.question, args.sidecar)
    elif args.command == "run":
        run(load_questions(), set(args.only) if args.only else None, args.repeats)
    elif args.command == "pilot":
        q = {q["id"]: q for q in load_questions()}[args.question_id]
        status = run_one(CONDITIONS[args.condition], q, 1, PILOT_DIR)
        print(f"[pilot] {status}")
    elif args.command == "citations":
        citations(args.n)
    elif args.command == "blind":
        blind()
    elif args.command == "summary":
        summary()


if __name__ == "__main__":
    main()
