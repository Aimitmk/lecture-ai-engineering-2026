"""第4回: 採点（app/judge.py）の配線テスト。API キーは使わない。

--model test と同じ偽モデル（規則で判定する FunctionModel）で、評価セット 10 件の
「採点 → 人のラベルとの比較 → 要確認・不一致の集計」が通ることを確かめる。
"""

from app import judge
from app.judge import (
    ALL_CRITERIA,
    DEFAULT_CASES,
    DEFAULT_RUBRIC,
    build_judge,
    build_test_model,
    check_lecture_mark,
    judge_cases,
    load_labels,
    overall,
    read_jsonl,
    summarize,
)

INSTRUCTOR_LABELS = judge.ROOT / "lectures" / "04" / "reference" / "labels_instructor.jsonl"


def test_lecture_mark_is_checked_by_code():
    assert check_lecture_mark("LoRA は…\n\n関係する回：第2回") == "pass"
    assert check_lecture_mark("第2回で扱う LoRA は…\n\n以上です。") == "fail"  # 末尾に無ければ fail
    assert check_lecture_mark("") == "fail"


def test_overall_requires_all_required_criteria():
    base = {"grounding": "pass", "scope": "pass", "hint": "pass", "lecture_mark": "pass", "clarity": "fail"}
    assert overall(base) == "pass"  # 分かりやすさは総合に入れない
    assert overall({**base, "hint": "fail"}) == "fail"
    assert overall({**base, "grounding": "unsure"}) == "unsure"


def test_cases_and_rubric_are_consistent():
    cases = read_jsonl(DEFAULT_CASES)
    assert len(cases) == 10
    assert len({c["id"] for c in cases}) == 10
    for c in cases:
        assert c["question"] and c["answer"] and c["reference"]["expected"]
    rubric = DEFAULT_RUBRIC.read_text(encoding="utf-8")
    for key, name in ALL_CRITERIA[:-1]:  # 回の表示はコードで判定するので rubric には書かない
        assert f"{name}（{key}）" in rubric
    labels = load_labels(INSTRUCTOR_LABELS)
    assert set(labels) == {c["id"] for c in cases}


def test_judge_pipeline_with_fake_model():
    cases = read_jsonl(DEFAULT_CASES)
    labels = load_labels(INSTRUCTOR_LABELS)
    agent = build_judge(build_test_model(), DEFAULT_RUBRIC.read_text(encoding="utf-8"))

    verdicts = judge_cases(agent, cases)
    assert set(verdicts) == {c["id"] for c in cases}
    for v in verdicts.values():
        for key, _ in ALL_CRITERIA:
            assert v[key]["verdict"] in ("pass", "fail", "unsure")
            assert v[key]["reason"]

    summary = summarize(cases, verdicts, labels)
    assert summary["n"] == 10
    # unsure にした項目は一致率の分母から外れ、要確認に入る
    excluded = sum(p["total"] - p["compared"] for p in summary["per_criterion"].values())
    assert excluded == len(summary["review"])
    assert summary["coverage"]["covered"] + len({r["id"] for r in summary["review"]}) == 10
    for m in summary["mismatches"]:
        assert m["kind"] in ("見逃し", "過検出")


# ---------------------------------------------------------------- 宿題（実装）: 自分のエージェントで回答を生成する
def _generate_with(monkeypatch, tmp_path, call_tools):
    """app.agent のモデルを TestModel（API を呼ばない偽モデル）にして、1 件だけ回答を生成する。"""
    from pydantic_ai.models.test import TestModel

    from app import agent as agent_module
    from app import tools

    log_dir = tmp_path / "learning_log"
    monkeypatch.setattr(tools, "LOG_DIR", log_dir)
    monkeypatch.setattr(agent_module, "build_model", lambda: TestModel(call_tools=call_tools))
    [case] = judge.generate_answers([{"id": "01", "question": "LoRAの要点を学習の記録に保存して", "answer": ""}], wait=0)
    return case, log_dir


def test_generate_denies_tools_that_need_approval(monkeypatch, tmp_path):
    """承認が要る save_learning_log が呼ばれても、評価では保存せず、断ったうえでの回答を残す。"""
    case, log_dir = _generate_with(monkeypatch, tmp_path, ["save_learning_log"])
    assert isinstance(case["answer"], str)
    assert not case["answer"].startswith("DeferredToolRequests")  # 直す前は承認待ちの repr が回答になっていた
    assert [r["tool"] for r in case["approval_requests"]] == ["save_learning_log"]
    assert "save_learning_log" in [c["tool"] for c in case["tool_calls"]]
    assert not log_dir.exists()  # 何も保存していない


def test_generate_records_tool_calls(monkeypatch, tmp_path):
    case, _ = _generate_with(monkeypatch, tmp_path, ["search_glossary"])
    assert [c["tool"] for c in case["tool_calls"]] == ["search_glossary"]
    assert case["approval_requests"] == []
