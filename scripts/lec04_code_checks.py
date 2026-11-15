"""第4回 宿題（実装）: 自分の評価セットで、コードで決まる基準を判定する（LLM は呼ばない）。

app.judge --generate が残したツール呼び出し（tool_calls）と承認待ち（approval_requests）、
評価セットの「期待するツール」（reference.tools）から、次の 3 つを判定して表にする。

- ツール：期待したツールをすべて呼んだか（reference.tools が空の件は判定しない）
- 承認：承認が要るツール（requires_approval=True）を、頼まれた件では承認を求めてから呼んだか、
  頼まれていない件では呼ぼうとしなかったか
- 回の表示：末尾（最後の行）に「第N回」があるか（app.judge.check_lecture_mark と同じ）

LLM の採点者に渡るのは「質問・回答・参照」の文だけなので、ツールの道筋や承認の有無は LLM からは見えない。

使い方（リポジトリの直下で）:
    uv run --frozen python -m scripts.lec04_code_checks    # results/impl/code_checks.md を書く
"""

from pathlib import Path

from pydantic_ai.toolsets import FunctionToolset

from app.agent import agent
from app.judge import check_lecture_mark, load_labels, read_jsonl

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "data" / "eval" / "my_cases.jsonl"
LABELS = ROOT / "lectures" / "04" / "my_labels.jsonl"
OUT = ROOT / "lectures" / "04" / "results" / "impl" / "code_checks.md"


def approval_tools() -> set[str]:
    """agent.py で requires_approval=True を付けて登録したツールの名前。"""
    [toolset] = [t for t in agent.toolsets if isinstance(t, FunctionToolset)]
    return {name for name, tool in toolset.tools.items() if tool.requires_approval}


def check(case: dict, needs_approval: set[str]) -> dict:
    called = [c["tool"] for c in case.get("tool_calls", [])]
    asked = [r["tool"] for r in case.get("approval_requests", [])]
    expected = case["reference"].get("tools", [])
    tools_ok = None if not expected else all(t in called for t in expected)
    expected_approval = [t for t in expected if t in needs_approval]
    if expected_approval:  # 頼まれた件：承認を求めてから呼んだか
        approval_ok = all(t in asked for t in expected_approval)
    else:  # 頼まれていない件：承認が要るツールを呼ぼうとしなかったか
        approval_ok = not any(t in needs_approval for t in called)
    return {"called": called, "asked": asked, "expected": expected, "tools": tools_ok,
            "approval": approval_ok, "lecture_mark": check_lecture_mark(case["answer"])}


def mark(value) -> str:
    return "—" if value is None else ("pass" if value is True else "fail" if value is False else value)


def main() -> None:
    cases = read_jsonl(CASES)
    labels = load_labels(LABELS) if LABELS.exists() else {}
    needs_approval = approval_tools()
    rows = [(c, check(c, needs_approval)) for c in cases]
    lines = [
        "# 第4回 宿題（実装）: コードで決まる基準の判定",
        "",
        f"- 評価セット：`data/eval/my_cases.jsonl`（回答は第3回のエージェントで生成）。承認が要るツール：{', '.join(sorted(needs_approval))}",
        "- 「ツール」は reference.tools のツールをすべて呼んだか（— は期待するツールを決めていない件）",
        "- 「承認」は、保存を頼まれた件では承認を求めたか、頼まれていない件では承認が要るツールを呼ぼうとしなかったか",
        "- 「回の表示」はコードの判定（最後の行に第N回）と、Claude のラベル",
        "- この表は `uv run --frozen python -m scripts.lec04_code_checks` で作り直せる（LLM は呼ばない）",
        "",
        "| # | 種類 | 期待するツール | 呼んだツール | 承認を求めた | ツール | 承認 | 回の表示（コード） | 回の表示（Claude のラベル） |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c, r in rows:
        label = labels.get(c["id"], {}).get("lecture_mark", "")
        lines.append(
            f"| {c['id']} | {c.get('category', '')} | {', '.join(r['expected']) or '（なし）'} | "
            f"{', '.join(r['called']) or '（なし）'} | {', '.join(r['asked']) or '—'} | "
            f"{mark(r['tools'])} | {mark(r['approval'])} | {r['lecture_mark']} | {label} |"
        )
    judged = [r for _, r in rows if r["tools"] is not None]
    lines += [
        "",
        f"- ツール：{sum(r['tools'] for r in judged)}/{len(judged)} 件で、期待したツールを呼んだ",
        f"- 承認：{sum(r['approval'] for _, r in rows)}/{len(rows)} 件が pass",
        f"- 回の表示：コードと Claude のラベルが {sum(r['lecture_mark'] == labels.get(c['id'], {}).get('lecture_mark') for c, r in rows)}/{len(rows)} 件で一致",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
