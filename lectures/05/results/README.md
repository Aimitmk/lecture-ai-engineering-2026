# 第5回 実行の記録

[answer.md](../answer.md) の数字は、ここにあるファイルから出している。表は `scripts/lec05_runs.py summary` で作り直せる（API は呼ばない）。

| フォルダ | 中身 |
|---|---|
| [probe/](probe/) | 質問セットを決めるための、検索だけの事前調査（`scripts/lec05_probe.py`、生成 API なし）と、pilot（K=5 のエージェントを 1 回ずつ。表には使わない） |
| [runs/](runs/) | 本番の実行。1 回ごとに `<条件>__<質問>__<回>.txt`（CLI の `--trace` と同じ表示）と `.json`（本文を渡したページ・ツールの引数・usage など）。`run_log.txt` は実行順と時刻 |
| [exercise/](exercise/) | 演習：変更前のテスト、ツール一覧、STEP 2 の検索だけの出力、表（summary.md） |
| [basic/](basic/) | 基礎（RAG_TOP_K を 3・5・10）の表 |
| [impl/](impl/) | 実装（`--neighbors`）の表と、検索だけの出力 |
| [advanced/](advanced/) | 発展（`--outline`）の表と、ツール一覧 |
| [judge/](judge/) | 回答の判定。条件名を伏せて並べ替えた `blind.md` で判定し（`judgments.jsonl`）、`blind_key.json` で条件に戻した。指示は `judge_prompt.md`、本番の前の試し（pilot の 5 件）は `dryrun/` |
| [answer_tables.md](answer_tables.md) | answer.md に貼った表（`summary` が作る） |
| [notes_before_rep3.md](notes_before_rep3.md) | 1・2 回目を見た後、3 回目の前に決めた、結果の読み方 |

- 条件名：`vector`＝ベクトル検索 K=5（既定）、`full`＝全文投入、`tree`、`graph`、`k3`・`k10`＝RAG_TOP_K を 3・10、`neighbors`＝K=5＋前後 1 ページ、`outline`＝検索＋目次。
- 質問：[questions.json](../questions.json) の 7 問。全文投入・Tree・Graph は、演習の 3 問（lora・memory・none）だけで回した。
- `.fail<n>.txt` は、やり直した実行の記録（503 や 429 の本文）。やり直した後の結果だけを表に使う。
- `.json` にはページ本文と、全文投入の入力を入れていない（page_id から `data/rag_data/lectures.json` で引ける）。
