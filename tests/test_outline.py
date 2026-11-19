"""第5回 宿題（発展）: 検索＋目次（--outline）のテスト（API は呼ばない）。"""

import json
import sys

from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models.test import TestModel

import app.agent as agent_module
from app import retrieval, tools


def page(doc: str, n: int, section: str) -> dict:
    return {"page_id": f"{doc}-p{n:03d}", "document_id": doc, "lecture": int(doc[3:5]),
            "document_title": f"講義{doc[3:5]}", "section": section, "title": f"見出し{n}",
            "page": n, "content": f"本文 {doc} {n}"}


PAGES = ([page("lec01-main", n, "章A" if n <= 2 else "章B") for n in range(1, 5)]
         + [page("lec02-main", n, "章C") for n in range(1, 4)])


def test_outline_lists_sections_and_titles_without_text():
    outline = retrieval.lecture_outline(["lec01-main"], {"lec01-main-p003"}, PAGES)
    assert len(outline) == 1 and outline[0]["lecture"] == 1
    assert [s["section"] for s in outline[0]["sections"]] == ["章A", "章B"]
    assert outline[0]["sections"][1]["pages"] == ["★p.3 見出し3［lec01-main-p003］", "p.4 見出し4［lec01-main-p004］"]
    assert "本文" not in json.dumps(outline, ensure_ascii=False)  # 目次に本文は入れない


def test_outline_follows_the_order_of_the_hits(monkeypatch):
    hits = [{**page("lec02-main", 2, "章C"), "distance": 0.1}, {**page("lec01-main", 4, "章B"), "distance": 0.2}]
    monkeypatch.setattr(retrieval, "search", lambda query: hits)
    monkeypatch.setattr(retrieval, "load_pages", lambda source=None: PAGES)
    data = retrieval.search_with_outline("質問")
    assert data["results"] == hits  # 本文は search() の結果のまま
    assert [d["document_id"] for d in data["outline"]] == ["lec02-main", "lec01-main"]


def test_read_pages_reads_target_pages_only_up_to_the_limit():
    data = retrieval.read_pages(["lec03-main-p013", "lec05-main-p001", "lec03-main-p013", "nope"], limit=2)
    # 重複は 1 回。第1〜3回の本講義に無い ID は not_found
    assert [p["page_id"] for p in data["pages"]] == ["lec03-main-p013"]
    assert data["pages"][0]["lecture"] == 3 and data["pages"][0]["page"] == 13 and data["pages"][0]["content"]
    assert data["not_found"] == ["lec05-main-p001"] and data["skipped"] == ["nope"]


def test_outline_tools_return_json(monkeypatch):
    monkeypatch.setattr(retrieval, "search", lambda query: [{**page("lec01-main", 3, "章B"), "distance": 0.1}])
    monkeypatch.setattr(retrieval, "load_pages", lambda source=None: PAGES)
    data = json.loads(tools.search_outline("質問"))
    assert data["results"][0]["page_id"] == "lec01-main-p003" and data["outline"][0]["document_id"] == "lec01-main"
    assert json.loads(tools.read_pages(["nope"]))["not_found"] == ["nope"]


def test_outline_mode_offers_two_tools(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["app.agent", "--outline", "--list-tools"])
    agent_module.main()
    out = capsys.readouterr().out
    assert "ツール: 2 個" in out and "[search_outline]" in out and "[read_pages]" in out
    assert '"page_ids": {"items": {"type": "string"}, "type": "array"}' in out


def test_outline_results_reach_the_model(monkeypatch):
    monkeypatch.setattr(retrieval, "search", lambda query: [{**page("lec01-main", 3, "章B"), "distance": 0.1}])
    monkeypatch.setattr(retrieval, "load_pages", lambda source=None: PAGES)
    model = TestModel(call_tools=["search_outline"])
    with agent_module.agent.override(model=model, instructions=agent_module.OUTLINE_INSTRUCTIONS,
                                     tools=[tools.search_outline, tools.read_pages]):
        result = agent_module.agent.run_sync("質問")
    returns = [p for m in result.all_messages() for p in m.parts if isinstance(p, ToolReturnPart)]
    assert returns[0].tool_name == "search_outline"
    assert json.loads(returns[0].content)["outline"][0]["sections"][1]["pages"][0].startswith("★p.3")
