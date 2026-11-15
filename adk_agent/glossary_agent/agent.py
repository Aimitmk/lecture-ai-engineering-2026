"""第3回 宿題（発展 a）: 演習と同じ指示とツールで、エージェントを組み立てる部分だけを ADK で書き直す。

動かす（リポジトリの直下で）:
    PYTHONPATH=. uv run --with google-adk adk run adk_agent/glossary_agent

app/agent.py（Pydantic AI 版）との違い:
- 指示（INSTRUCTIONS）とツールの関数は app/ のものをそのまま使い、app/ のファイルは変えない
- モデルは組み立てるときに決める（Pydantic AI 版は実行するときに渡す）。
  どちらも app.config.MODEL を使うので、環境変数 AIE_MODEL で同じように切り替わる
- ツールは関数のリストで渡す。docstring と型ヒントが説明文になるのは Pydantic AI 版と同じ
"""

from google.adk.agents import Agent

from app import tools
from app.agent import INSTRUCTIONS
from app.config import MODEL

root_agent = Agent(
    model=MODEL,
    name="glossary_agent",
    instruction=INSTRUCTIONS,
    # 演習で使ったツール。save_learning_log（宿題の実装）は入れない。承認の要否は Pydantic AI 側の
    # 登録（requires_approval=True）で決まっているので、関数をここにそのまま渡すと確認なしで保存してしまう
    tools=[tools.search_glossary, tools.get_lecture_summary, tools.make_quiz],
)
