"""第3回 宿題（実装）: 保存の前に利用者の承認を挟む save_learning_log のテスト。

TestModel（APIを呼ばない偽モデル）に save_learning_log を呼ばせ、
「承認されるまで保存されない」「承認したら保存される」「断ったら保存されず、モデルに伝わる」を確かめる。
保存先は一時フォルダに差し替えるので、learning_log/ には何も書かない。
"""

import pytest
from pydantic_ai import DeferredToolRequests, DeferredToolResults, ToolDenied
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.models.test import TestModel

from app import tools
from app.agent import DENIED_MESSAGE, agent, ask_approvals

TOOL = "save_learning_log"


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    path = tmp_path / "learning_log"
    monkeypatch.setattr(tools, "LOG_DIR", path)
    return path


def _saved(log_dir):
    return sorted(log_dir.glob("*.md")) if log_dir.exists() else []


def _returns(result):
    return [
        p for m in result.all_messages() for p in m.parts
        if isinstance(p, ToolReturnPart) and p.tool_name == TOOL
    ]


def _ask_to_save():
    with agent.override(model=TestModel(call_tools=[TOOL])):
        return agent.run_sync("今日の学びを記録して")


def _resume(first, approval):
    [call] = first.output.approvals
    with agent.override(model=TestModel(call_tools=[TOOL])):
        return agent.run_sync(
            message_history=first.all_messages(),
            deferred_tool_results=DeferredToolResults(approvals={call.tool_call_id: approval}),
        )


def test_save_learning_log_appends_to_the_file_of_the_day(log_dir):
    tools.save_learning_log("LoRA", "低ランク行列だけを学習する")
    message = tools.save_learning_log("QLoRA\nの違い", "量子化したモデルに LoRA を足して学習する")
    [path] = _saved(log_dir)
    text = path.read_text(encoding="utf-8")
    assert text.count("\n## ") + text.startswith("## ") == 2
    assert "QLoRA の違い" in text  # 見出しの改行は空白にする
    assert "保存しました" in message


def test_save_learning_log_does_not_save_empty_text(log_dir):
    assert "保存していません" in tools.save_learning_log("  ", "内容")
    assert "保存していません" in tools.save_learning_log("見出し", "\n")
    assert _saved(log_dir) == []


def test_the_call_waits_for_approval_and_nothing_is_saved_yet(log_dir):
    first = _ask_to_save()
    assert isinstance(first.output, DeferredToolRequests)
    assert [c.tool_name for c in first.output.approvals] == [TOOL]
    assert _returns(first) == []
    assert _saved(log_dir) == []


def test_approved_call_saves_and_the_run_finishes(log_dir):
    result = _resume(_ask_to_save(), True)
    assert isinstance(result.output, str)
    assert len(_saved(log_dir)) == 1
    assert "保存しました" in _returns(result)[0].content


def test_denied_call_does_not_save_and_the_model_is_told(log_dir):
    result = _resume(_ask_to_save(), ToolDenied(DENIED_MESSAGE))
    assert isinstance(result.output, str)
    assert _saved(log_dir) == []
    assert _returns(result)[0].content == DENIED_MESSAGE


def _requests():
    call = ToolCallPart(TOOL, {"title": "LoRA", "content": "低ランク行列"}, tool_call_id="call-1")
    return DeferredToolRequests(approvals=[call])


@pytest.mark.parametrize("answer, approved", [("y", True), ("Y", True), ("yes", True), ("n", False), ("", False), ("はい", False)])
def test_ask_approvals_follows_the_answer(monkeypatch, capsys, answer, approved):
    monkeypatch.setattr("builtins.input", lambda prompt="": answer)
    result = ask_approvals(_requests()).approvals["call-1"]
    if approved:
        assert result is True
    else:
        assert isinstance(result, ToolDenied) and result.message == DENIED_MESSAGE
    assert "低ランク行列" in capsys.readouterr().out  # 承認の前に、保存する内容を見せる


def test_ask_approvals_denies_when_there_is_no_input(monkeypatch):
    def no_input(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", no_input)
    assert isinstance(ask_approvals(_requests()).approvals["call-1"], ToolDenied)
