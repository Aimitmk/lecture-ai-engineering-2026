"""第1回: 素のLLMに質問するスクリプト。

使い方:
    uv run python -m app.ask "LoRAとは何ですか？"
    uv run python -m app.ask            # 質問を省略すると、講座に固有の質問をする
    uv run python -m app.ask --temperature 0 "LoRAとは何ですか？"  # 宿題（基礎）: temperature を指定する
    uv run python -m app.ask --chat     # 宿題（実装）: 会話履歴を保って続けて質問する（空行か exit で終了）

ツールも会話履歴も持たない「素の」呼び出し（--chat のときだけ会話履歴を持つ）。
講座に固有のことを聞くと、「分からない」と答えるか、一般論でもっともらしく答える
（講座の実際とは違う）ことを確かめよう。
（第3回で、用語集を検索できるエージェントにして改善する）
"""

import argparse
import sys

from google import genai
from google.genai import errors, types

from app.config import MODEL, api_error_message, get_api_key

# 講座に固有の質問。正しい答えは data/glossary.json の homework-levels にある
DEFAULT_QUESTION = "AIE2026の講座の宿題にある「3レベル」とは何ですか？"


def format_usage(usage: types.GenerateContentResponseUsageMetadata | None) -> str:
    """usage_metadata のトークン数を1行にする。

    思考（thoughts）は回答の本文には出ないが、出力（candidates）とは別に数えられ、合計に含まれる。
    値がない項目（思考しないモデルの thoughts など）は 0 とする。
    """
    if usage is None:
        return "[tokens] 取得できませんでした"
    return (
        f"[tokens] 入力 {usage.prompt_token_count or 0}"
        f" / 出力 {usage.candidates_token_count or 0}"
        f" / 思考 {usage.thoughts_token_count or 0}"
        f" / 合計 {usage.total_token_count or 0}"
    )


def build_config(temperature: float | None) -> types.GenerateContentConfig | None:
    """temperature を指定したときだけ config を作る（指定しなければモデルの既定値のまま）。"""
    if temperature is None:
        return None
    return types.GenerateContentConfig(temperature=temperature)


def ask(question: str, config: types.GenerateContentConfig | None = None) -> str:
    client = genai.Client(api_key=get_api_key())
    response = client.models.generate_content(model=MODEL, contents=question, config=config)

    # 第1回 演習: response.usage_metadata から入力トークン数と出力トークン数を表示する
    print(format_usage(response.usage_metadata))

    return response.text


def chat(config: types.GenerateContentConfig | None = None) -> None:
    """第1回 宿題（実装）: 会話履歴を保ったまま続けて質問する。

    API は前の会話を覚えていない。chat は、それまでの質問と回答（履歴）を
    毎回まとめて送り直すので、ターンを重ねるほど入力トークンが増える。
    """
    client = genai.Client(api_key=get_api_key())
    session = client.chats.create(model=MODEL, config=config)
    while True:
        try:
            question = input("\n[質問] ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not sys.stdin.isatty():
            print(question)  # パイプで質問を渡したときも、ログに質問を残す
        if question in ("", "exit", "quit"):
            break
        try:
            response = session.send_message(question)
        except errors.APIError as e:
            # 失敗したターンは履歴に入らないので、そのまま次の質問を受け付ける
            print(api_error_message(e.code, e.message))
            continue
        print(f"{format_usage(response.usage_metadata)} / 履歴 {len(session.get_history())} 件")
        print(response.text)


def main() -> None:
    parser = argparse.ArgumentParser(description="素のLLMに質問する")
    parser.add_argument("question", nargs="?")
    parser.add_argument("--temperature", type=float, help="宿題（基礎）: 生成のランダムさ（例: 0, 1, 2）")
    parser.add_argument("--chat", action="store_true", help="宿題（実装）: 会話履歴を保って続けて質問する")
    args = parser.parse_args()
    if args.chat and args.question:
        parser.error("--chat のときは、質問は起動したあとに入力してください")
    config = build_config(args.temperature)

    print(f"[model] {MODEL}")
    if args.temperature is not None:
        print(f"[temperature] {args.temperature}")
    if args.chat:
        print("[chat] 会話履歴を保って続けて質問できます（空行か exit で終了）")
        chat(config)
        return

    question = args.question or DEFAULT_QUESTION
    print(f"[質問] {question}\n")
    try:
        print(ask(question, config))
    except errors.APIError as e:
        print(api_error_message(e.code, e.message))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
