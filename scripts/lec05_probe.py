"""第5回: 質問セットを決めるための、検索だけの事前調査（生成 API は使わない）。

質問文をそのまま埋め込み（質問ごとに 1 回。結果は .cache/rag/ にキャッシュする）、
次の取得方法で、根拠ページが入るかを表にする。

- ベクトル検索の上位 K=3・5・10
- K=5 に前後 1 ページを足した集合（同じ資料の中だけ）
- 現状の Graph（seeds と expanded の 10 件。経路が前後ページか、用語か）と、2 hop の候補すべて
- K=5 の hit がある回の目次に、根拠ページが出るか（発展の既定案「検索＋目次」）

使い方（リポジトリの直下で）:
    uv run --frozen --env-file .env python -m scripts.lec05_probe lectures/05/results/probe/candidates.json
"""

import argparse
import json
from pathlib import Path

from app import retrieval

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "lectures" / "05" / "results" / "probe"
CACHE = ROOT / ".cache" / "rag" / "lec05_query_vectors.json"


def label(page_id: str) -> str:
    """lec03-main-p013 → 第3回p.13"""
    return f"第{int(page_id[3:5])}回p.{int(page_id.rsplit('-p', 1)[1])}"


def cached_embedder(original):
    """同じ文の埋め込みは、API を呼ばずにキャッシュから返す。"""
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}

    def embed(text: str, task_type: str) -> list[float]:
        key = f"{task_type}\n{text}"
        if key not in cache:
            cache[key] = original(text, task_type)
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(cache), encoding="utf-8")
        return cache[key]

    return embed


def with_neighbors(hit_ids: list[str], pages: list[dict], window: int = 1) -> list[str]:
    """hit に、同じ資料の中の前後 window ページを足す（重複なし。実装の --neighbors と同じ考え方）。"""
    position = {page["page_id"]: i for i, page in enumerate(pages)}
    result = list(hit_ids)
    for page_id in hit_ids:
        i = position[page_id]
        for j in range(i - window, i + window + 1):
            if 0 <= j < len(pages) and pages[j]["document_id"] == pages[i]["document_id"]:
                if pages[j]["page_id"] not in result:
                    result.append(pages[j]["page_id"])
    return result


def graph_result(question: str, max_results: int) -> dict:
    original = retrieval.GRAPH_MAX_RESULTS
    retrieval.GRAPH_MAX_RESULTS = max_results
    try:
        return retrieval.search_graph(question)
    finally:
        retrieval.GRAPH_MAX_RESULTS = original


def via(path: list[dict]) -> str:
    terms = [node["title"] for node in path if node["id"].startswith("term:")]
    return f"用語「{terms[0]}」" if terms else "前後ページ"


def probe(candidate: dict, pages: list[dict]) -> dict:
    question = candidate["question"]
    retrieval.RAG_TOP_K = 10
    top10 = retrieval.search(question)
    retrieval.RAG_TOP_K = 5
    ranking = [hit["page_id"] for hit in top10]
    graph10 = graph_result(question, retrieval.GRAPH_MAX_RESULTS)
    graph_all = graph_result(question, 10_000)
    hit_documents = {page_id.rsplit("-p", 1)[0] for page_id in ranking[:5]}
    sets = {
        "K=3": ranking[:3],
        "K=5": ranking[:5],
        "K=10": ranking[:10],
        "前後1": with_neighbors(ranking[:5], pages),
        "Graph": [p["page_id"] for p in graph10["seeds"] + graph10["expanded"]],
        "Graph全候補": [p["page_id"] for p in graph_all["seeds"] + graph_all["expanded"]],
        "目次": [p["page_id"] for p in pages if p["document_id"] in hit_documents],
    }
    return {
        **candidate,
        "top10": [{"rank": i, "page_id": hit["page_id"], "title": hit["title"],
                   "distance": round(hit["distance"], 4)} for i, hit in enumerate(top10, 1)],
        "graph": [{"page_id": p["page_id"], "role": role, "hops": p["hops"], "via": via(p["path"])}
                  for role in ("seeds", "expanded") for p in graph10[role]],
        "graph_candidates": len(graph_all["seeds"]) + len(graph_all["expanded"]),
        "sets": sets,
        "found": {name: {gold: gold in ids for gold in candidate["gold"]} for name, ids in sets.items()},
    }


def to_markdown(results: list[dict]) -> str:
    names = ["K=3", "K=5", "K=10", "前後1", "Graph", "Graph全候補", "目次"]
    lines = [
        "# 第5回 事前調査：根拠ページが入るか（検索だけ・生成 API なし）",
        "",
        "- 質問文をそのまま埋め込み（gemini-embedding-001、768 次元、同梱の index.sqlite3）、各方式の集合に根拠ページが入るかを見た。",
        "- 前後1：K=5 の hit に、同じ資料の前後 1 ページを足した集合（最大 15 ページ）。",
        "- Graph：現状の search_graph が返す 10 件（seeds 3＋expanded 7）。Graph全候補：同じ 2 hop で届く候補すべて。",
        "- 目次：K=5 の hit がある回の全ページ（見出しが目次に出るので、エージェントが選べば読める）。",
        "- エージェントは自分で検索語を決めるので、ここでの取りこぼしが、そのまま回答の取りこぼしになるとは限らない。",
        "",
        "| 質問 | 種類 | 根拠 | " + " | ".join(names) + " |",
        "|---|---|---|" + "---|" * len(names),
    ]
    for r in results:
        if not r["gold"]:
            lines.append(f"| {r['id']} | {r['kind']} | なし | " + " | ".join("－" for _ in names) + " |")
            continue
        cells = []
        for name in names:
            got = [g for g in r["gold"] if r["found"][name][g]]
            cells.append(f"{len(got)}/{len(r['gold'])}" + ("" if len(got) == len(r["gold"]) else
                         "（欠：" + "・".join(label(g) for g in r["gold"] if g not in got) + "）"))
        lines.append(f"| {r['id']} | {r['kind']} | {'・'.join(label(g) for g in r['gold'])} | "
                     + " | ".join(cells) + " |")
    for r in results:
        lines += ["", f"## {r['id']}：{r['question']}", "",
                  f"根拠：{'・'.join(label(g) for g in r['gold']) or 'なし'}", "",
                  "| 順位 | ページ | 見出し | 距離 | 根拠 |", "|---|---|---|---|---|"]
        for hit in r["top10"]:
            lines.append(f"| {hit['rank']} | {label(hit['page_id'])} | {hit['title']} | {hit['distance']} | "
                         f"{'◎' if hit['page_id'] in r['gold'] else ''} |")
        lines += ["", f"Graph（2 hop の候補 {r['graph_candidates']} 件のうち、返る 10 件）：", ""]
        for p in r["graph"]:
            mark = "◎" if p["page_id"] in r["gold"] else ""
            lines.append(f"- {p['role']} {label(p['page_id'])}（{p['hops']} hop・{p['via']}）{mark}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates", type=Path)
    args = parser.parse_args()
    retrieval.embed_text = cached_embedder(retrieval.embed_text)
    pages = retrieval.load_pages()
    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    if isinstance(candidates, dict):  # lectures/05/questions.json の形
        candidates = candidates["questions"]
    results = [probe(candidate, pages) for candidate in candidates]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"probe_{args.candidates.stem}"
    (OUT_DIR / f"{name}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / f"{name}.md").write_text(to_markdown(results), encoding="utf-8")
    print(to_markdown(results).split("\n## ")[0])


if __name__ == "__main__":
    main()
