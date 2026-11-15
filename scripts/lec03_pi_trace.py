"""第3回 宿題（発展 b）: Pi の `--mode json` の出力（JSONL）から、読みやすい trace を作る。

`app.agent --trace` と同じように、ツールの呼び出しと戻り値、LLM の応答ごとのトークン、最終回答を並べる。
標準ライブラリだけで動く（API キー不要）。

使い方（リポジトリの直下で）:
    python scripts/lec03_pi_trace.py lectures/03/results/pi/save.jsonl --meta lectures/03/results/pi/save.meta

--written-list（marker より新しかったファイルの一覧）と --written（そのコピー）は、Codespace の中で
run_one.sh が作ったもの。commit していないので、作り直した trace には、その節が出ない。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def text_of(content) -> str:
    """メッセージやツールの戻り値の content から、テキストの部分だけをつなげる。"""
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def short(s: str, n: int = 300) -> str:
    s = s.replace("\n", "\\n")
    return s if len(s) <= n else s[:n] + "…"


def build(jsonl: Path, meta: Path | None, written_list: Path | None, written: Path | None) -> str:
    events = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    lines: list[str] = []
    if meta and meta.exists():
        lines += meta.read_text(encoding="utf-8").splitlines() + [""]

    assistants = []
    tool_calls = 0
    lines.append("--- trace ---")
    for e in events:
        t = e.get("type")
        if t == "tool_execution_start":
            tool_calls += 1
            lines.append(f"[tool call]   {e.get('toolName')}({json.dumps(e.get('args'), ensure_ascii=False)})")
        elif t == "tool_execution_end":
            err = "（エラー）" if e.get("isError") else ""
            res = text_of((e.get("result") or {}).get("content"))
            lines.append(f"[tool return] {e.get('toolName')}{err} -> {short(res)}")
        elif t == "message_end" and (e.get("message") or {}).get("role") == "assistant":
            m = e["message"]
            assistants.append(m)
            u = m.get("usage") or {}
            calls = [b for b in m.get("content") or [] if b.get("type") == "toolCall"]
            txt = text_of(m.get("content"))
            lines.append(
                f"[LLM {len(assistants)}] {m.get('provider')}/{m.get('model')} stop={m.get('stopReason')} "
                f"input={u.get('input')} cacheRead={u.get('cacheRead')} output={u.get('output')} "
                f"reasoning={u.get('reasoning', 0)} toolCall={len(calls)}"
                + (f" text={short(txt, 120)}" if txt else "")
            )
        elif t in ("auto_retry_start", "auto_retry_end"):
            lines.append(f"[{t}] {json.dumps({k: v for k, v in e.items() if k != 'type'}, ensure_ascii=False)}")

    def total(key: str) -> int:
        return sum((m.get("usage") or {}).get(key, 0) or 0 for m in assistants)

    turns = sum(1 for e in events if e.get("type") == "turn_end")
    lines += [
        "",
        f"[usage] LLM の応答={len(assistants)} turn={turns} ツールの実行={tool_calls} "
        f"input_tokens={total('input')} cacheRead={total('cacheRead')} "
        f"output_tokens={total('output')}（うち reasoning={total('reasoning')}）",
        "",
        "--- 最終回答 ---",
        text_of(assistants[-1].get("content")) if assistants else "（応答なし）",
    ]

    if written_list is not None and written_list.exists():
        paths = [p for p in written_list.read_text(encoding="utf-8").splitlines() if p.strip()]
        noise = ("/.venv/", "/__pycache__/", "/.pytest_cache/")
        kept = [p for p in paths if not any(n in p for n in noise)]
        lines += [
            "",
            f"--- 実行の後に、実行の前の marker より新しかったファイル：{len(paths)} 件 ---",
            f"（.venv・__pycache__・.pytest_cache の {len(paths) - len(kept)} 件は、uv run と pytest が作ったもの。下には出さない）",
            *kept,
        ]
    if written is not None and written.exists():
        for p in sorted(p for p in written.rglob("*") if p.is_file()):
            lines += ["", f"## 中身：/{p.relative_to(written).as_posix()}", p.read_text(encoding="utf-8", errors="replace").rstrip()]
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("jsonl", type=Path)
    ap.add_argument("--meta", type=Path, help="run_one.sh が書いた、実行の条件と時刻")
    ap.add_argument("--written-list", type=Path, help="marker より新しかったファイルの一覧（find の結果）")
    ap.add_argument("--written", type=Path, help="Pi が書いたファイルのコピーを置いたフォルダ")
    args = ap.parse_args()
    print(build(args.jsonl, args.meta, args.written_list, args.written), end="")


if __name__ == "__main__":
    main()
