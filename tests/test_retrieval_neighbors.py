"""第5回 宿題（実装）: 検索結果に前後1ページの本文を足す処理のテスト（API は呼ばない）。"""

import json
import sys

from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models.test import TestModel

import app.agent as agent_module
from app import retrieval, tools


def page(doc: str, n: int) -> dict:
    return {"page_id": f"{doc}-p{n:03d}", "document_id": doc, "lecture": int(doc[3:5]),
            "document_title": f"講義{doc[3:5]}", "section": "章", "title": f"見出し{n}",
            "page": n, "content": f"本文 {doc} {n}"}


# 2 つの資料が続けて並ぶ（load_pages() と同じ形）
PAGES = [page("lec01-main", n) for n in range(1, 6)] + [page("lec02-main", n) for n in range(1, 6)]


def hit(doc: str, n: int, distance: float = 0.1) -> dict:
    return {**page(doc, n), "distance": distance}


def ids(results: list[dict]) -> list[str]:
    return [r["page_id"] for r in results]


def test_adds_previous_and_next_page_with_text_and_citation():
    results = retrieval.add_neighbor_pages([hit("lec01-main", 3)], 1, PAGES)
    assert ids(results) == ["lec01-main-p002", "lec01-main-p003", "lec01-main-p004"]
    assert results[1]["rank"] == 1 and results[1]["distance"] == 0.1
    assert results[0]["neighbor_of"] == results[2]["neighbor_of"] == "lec01-main-p003"
    assert "distance" not in results[0] and "rank" not in results[0]
    # 足したページにも、本文と引用に必要な情報（講義・章・見出し・ページ）がある
    assert results[0]["content"] == "本文 lec01-main 2"
    assert {"lecture", "section", "title", "page"} <= results[0].keys()


def test_first_and_last_pages_do_not_cross_documents():
    results = retrieval.add_neighbor_pages([hit("lec01-main", 5), hit("lec02-main", 1)], 1, PAGES)
    # lec01 の最後のページの「次」に、lec02 の 1 ページ目を足さない（逆も同じ）
    assert ids(results) == ["lec01-main-p004", "lec01-main-p005", "lec02-main-p001", "lec02-main-p002"]
    assert results[2]["rank"] == 2 and "neighbor_of" not in results[2]


def test_adjacent_hits_are_one_block_without_duplicates():
    results = retrieval.add_neighbor_pages([hit("lec01-main", 3), hit("lec01-main", 2)], 1, PAGES)
    assert ids(results) == ["lec01-main-p001", "lec01-main-p002", "lec01-main-p003", "lec01-main-p004"]
    # 隣が別の hit のときは、隣としては足さない（hit のまま、順位を持つ）
    assert [r.get("rank") for r in results] == [None, 2, 1, None]


def test_shared_neighbor_is_added_once():
    results = retrieval.add_neighbor_pages([hit("lec01-main", 2), hit("lec01-main", 4)], 1, PAGES)
    assert ids(results) == [f"lec01-main-p00{n}" for n in range(1, 6)]
    # 2 つの hit に共通の隣（p.3）は 1 回だけ。近さが同じなら、順位の高い hit の隣とする
    assert results[2]["neighbor_of"] == "lec01-main-p002"


def test_blocks_follow_the_rank_of_their_hits():
    results = retrieval.add_neighbor_pages([hit("lec02-main", 3), hit("lec01-main", 3)], 1, PAGES)
    assert ids(results) == ["lec02-main-p002", "lec02-main-p003", "lec02-main-p004",
                            "lec01-main-p002", "lec01-main-p003", "lec01-main-p004"]


def test_window_zero_returns_the_hits_only():
    hits = [hit("lec01-main", 3), hit("lec02-main", 4)]
    assert ids(retrieval.add_neighbor_pages(hits, 0, PAGES)) == ids(hits)


def test_pages_outside_the_target_documents_are_not_added(tmp_path, monkeypatch):
    # 検索対象外の資料（lec05-main）は load_pages() で除かれるので、隣としても足さない
    source = tmp_path / "lectures.json"
    source.write_text(json.dumps([
        {"id": doc, "title": doc, "content": [{"section": "章", "content": [
            {"id": f"{doc}-p{n:03d}", "title": f"見出し{n}", "page": n, "content": f"本文{n}"}
            for n in (1, 2)]}]}
        for doc in ("lec03-main", "lec05-main")
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(retrieval, "RAG_SOURCE", source)
    results = retrieval.add_neighbor_pages([hit("lec03-main", 2)], 1)
    assert ids(results) == ["lec03-main-p001", "lec03-main-p002"]


def test_tool_returns_hits_and_neighbors(monkeypatch):
    monkeypatch.setattr(retrieval, "search", lambda query: [hit("lec01-main", 3)])
    monkeypatch.setattr(retrieval, "load_pages", lambda source=None: PAGES)
    data = json.loads(tools.search_materials_with_neighbors("質問"))
    assert ids(data["results"]) == ["lec01-main-p002", "lec01-main-p003", "lec01-main-p004"]


def list_tools(monkeypatch, capsys, *flags: str) -> str:
    monkeypatch.setattr(sys, "argv", ["app.agent", *flags, "--list-tools"])
    agent_module.main()
    return capsys.readouterr().out


def test_neighbors_mode_shows_the_model_the_same_tool(monkeypatch, capsys):
    # 名前・説明文・引数が通常と同じなので、変わるのは返すページの範囲だけ
    normal = list_tools(monkeypatch, capsys)
    assert "[search_materials]" in normal
    assert list_tools(monkeypatch, capsys, "--neighbors") == normal


def test_neighbors_tool_result_reaches_the_model(monkeypatch):
    monkeypatch.setattr(retrieval, "search", lambda query: [hit("lec01-main", 3)])
    monkeypatch.setattr(retrieval, "load_pages", lambda source=None: PAGES)
    model = TestModel(call_tools=["search_materials"])
    with agent_module.agent.override(model=model, tools=[agent_module.NEIGHBORS_TOOL]):
        result = agent_module.agent.run_sync("LoRAとは？")
    returns = [p for m in result.all_messages() for p in m.parts if isinstance(p, ToolReturnPart)]
    assert returns and returns[0].tool_name == "search_materials"
    assert ids(json.loads(returns[0].content)["results"]) == ["lec01-main-p002", "lec01-main-p003",
                                                              "lec01-main-p004"]
