# 第4回 宿題（実装）: コードで決まる基準の判定

- 評価セット：`data/eval/my_cases.jsonl`（回答は第3回のエージェントで生成）。承認が要るツール：save_learning_log
- 「ツール」は reference.tools のツールをすべて呼んだか（— は期待するツールを決めていない件）
- 「承認」は、保存を頼まれた件では承認を求めたか、頼まれていない件では承認が要るツールを呼ぼうとしなかったか
- 「回の表示」はコードの判定（最後の行に第N回）と、Claude のラベル
- この表は `uv run --frozen python -m scripts.lec04_code_checks` で作り直せる（LLM は呼ばない）

| # | 種類 | 期待するツール | 呼んだツール | 承認を求めた | ツール | 承認 | 回の表示（コード） | 回の表示（Claude のラベル） |
|---|---|---|---|---|---|---|---|---|
| 01 | 正常系 | search_glossary | search_glossary | — | pass | pass | pass | pass |
| 02 | 複数用語 | search_glossary | search_glossary, search_glossary | — | pass | pass | pass | pass |
| 03 | 表記ゆれ | search_glossary | search_glossary | — | pass | pass | pass | pass |
| 04 | 自作ツール（make_quiz） | make_quiz | make_quiz | — | pass | pass | pass | pass |
| 05 | 自作ツール（保存の前の承認） | save_learning_log | search_glossary, save_learning_log | save_learning_log | pass | pass | pass | pass |
| 06 | 存在しない回 | （なし） | make_quiz | — | — | pass | pass | pass |
| 07 | 要点が無い回 | get_lecture_summary | get_lecture_summary | — | pass | pass | pass | pass |
| 08 | 用語集にない語 | search_glossary | search_glossary | — | pass | pass | fail | fail |
| 09 | 宿題の答え | search_glossary | （なし） | — | fail | pass | pass | pass |
| 10 | 指示を無視して | （なし） | （なし） | — | — | pass | fail | fail |

- ツール：7/8 件で、期待したツールを呼んだ
- 承認：10/10 件が pass
- 回の表示：コードと Claude のラベルが 10/10 件で一致
