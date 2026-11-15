# 第4回 宿題（基礎）: 1 つずつ変えて再採点した結果

- ラベル：`lectures/04/labels.jsonl`（Claude のラベル、10 件）。評価セット：`data/eval/lec04_cases.jsonl`
- 一致率は「一致 / 比べた件数」。LLM が unsure にした項目は分母から外れる（演習と同じ）
- この表は `uv run --frozen python -m scripts.lec04_judge_variants --summary` で、runs/ の JSON から作り直せる

## 条件

| 条件 | 変えたこと |
|---|---|
| baseline | 変更なし（STEP 3 の後の rubric.md、gemini-3.5-flash-lite、理由→判定） |
| model_flash | 採点のモデルを gemini-3.5-flash にする |
| rubric_grounding | rubric.md の「根拠」の先頭に、内容だけを見て他の基準（ヒント・範囲）の理由を持ち込まない、と 1 行書き足す |
| order_schema | 出力の型（CriterionVerdict）の reason と verdict の順だけを入れ替える（説明文はそのまま） |
| order_all | 出力の型の順を入れ替え、「理由を先に」と書いた 3 か所（rubric.md の採点のしかた・出力の形式の文・CriterionVerdict の docstring）も「判定を先に」にする |

## 基準別の一致率（run ごと）

| 条件 | run | 根拠 | 範囲 | ヒント | 分かりやすさ | 回の表示 | 要確認 | 総合 | coverage | モデル（応答の記録） |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 1 | 8/10 | 9/10 | 10/10 | 9/10 | 10/10 | 0 | 10/10 | 10/10 | gemini-3.5-flash-lite |
| baseline | 2 | 9/10 | 10/10 | 10/10 | 8/10 | 10/10 | 0 | 10/10 | 10/10 | gemini-3.5-flash-lite |
| baseline | 3 | 8/10 | 10/10 | 10/10 | 10/10 | 10/10 | 0 | 10/10 | 10/10 | gemini-3.5-flash-lite |
| model_flash | 1 | 9/10 | 10/10 | 10/10 | 10/10 | 10/10 | 0 | 10/10 | 10/10 | gemini-3.6-flash |
| rubric_grounding | 1 | 9/10 | 10/10 | 10/10 | 10/10 | 10/10 | 0 | 10/10 | 10/10 | gemini-3.5-flash-lite |
| rubric_grounding | 2 | 9/10 | 10/10 | 10/10 | 10/10 | 10/10 | 0 | 10/10 | 10/10 | gemini-3.5-flash-lite |
| rubric_grounding | 3 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 0 | 10/10 | 10/10 | gemini-3.5-flash-lite |
| order_schema | 1 | 8/10 | 10/10 | 10/10 | 10/10 | 10/10 | 0 | 10/10 | 10/10 | gemini-3.5-flash-lite |
| order_schema | 2 | 9/10 | 10/10 | 10/10 | 10/10 | 10/10 | 0 | 10/10 | 10/10 | gemini-3.5-flash-lite |
| order_schema | 3 | 9/10 | 10/10 | 10/10 | 10/10 | 10/10 | 0 | 10/10 | 10/10 | gemini-3.5-flash-lite |
| order_all | 1 | 8/10 | 10/10 | 10/10 | 9/10 | 10/10 | 0 | 10/10 | 10/10 | gemini-3.5-flash-lite |
| order_all | 2 | 8/10 | 10/10 | 10/10 | 10/10 | 10/10 | 0 | 10/10 | 10/10 | gemini-3.5-flash-lite |
| order_all | 3 | 9/10 | 10/10 | 10/10 | 8/10 | 10/10 | 0 | 10/10 | 10/10 | gemini-3.5-flash-lite |

## 合計（全 run）と、不合格の再現率

不合格の再現率：ラベルが fail の項目のうち、LLM も fail にした割合（unsure は除く）。ラベルが fail の項目は 根拠 #10・範囲 #08・ヒント #06・分かりやすさ #04 だけなので、分母は小さい（各 run で 1 件ずつ）。

| 条件 | run 数 | 根拠 | 範囲 | ヒント | 分かりやすさ | 要確認（計） | 不合格の再現率（根拠 / 範囲 / ヒント / 分かりやすさ） | 過検出（計） |
|---|---|---|---|---|---|---|---|---|
| baseline | 3 | 25/30 | 29/30 | 30/30 | 27/30 | 0 | 3/3 / 3/3 / 3/3 / 2/3 | 8 |
| model_flash | 1 | 9/10 | 10/10 | 10/10 | 10/10 | 0 | 1/1 / 1/1 / 1/1 / 1/1 | 1 |
| rubric_grounding | 3 | 28/30 | 30/30 | 30/30 | 30/30 | 0 | 3/3 / 3/3 / 3/3 / 3/3 | 2 |
| order_schema | 3 | 26/30 | 30/30 | 30/30 | 30/30 | 0 | 3/3 / 3/3 / 3/3 / 3/3 | 4 |
| order_all | 3 | 25/30 | 30/30 | 30/30 | 27/30 | 0 | 3/3 / 3/3 / 3/3 / 3/3 | 8 |

## 不一致と要確認の中身（全 run）

- **baseline**：#04 分かりやすさ 見逃し（LLM=pass） ×1/3、#06 分かりやすさ 過検出（LLM=fail） ×1/3、#06 根拠 過検出（LLM=fail） ×2/3、#06 範囲 過検出（LLM=fail） ×1/3、#08 分かりやすさ 過検出（LLM=fail） ×1/3、#08 根拠 過検出（LLM=fail） ×3/3
- **model_flash**：#08 根拠 過検出（LLM=fail） ×1/1
- **rubric_grounding**：#08 根拠 過検出（LLM=fail） ×2/3
- **order_schema**：#06 根拠 過検出（LLM=fail） ×1/3、#08 根拠 過検出（LLM=fail） ×3/3
- **order_all**：#06 分かりやすさ 過検出（LLM=fail） ×2/3、#06 根拠 過検出（LLM=fail） ×2/3、#08 分かりやすさ 過検出（LLM=fail） ×1/3、#08 根拠 過検出（LLM=fail） ×3/3

## baseline（多数決）から判定が変わった項目

baseline の 3 回の多数決と比べ、各条件で判定が違った回数（「×回数/run 数」）。

- **baseline**：#04 分かりやすさ fail→pass ×1/3、#06 分かりやすさ pass→fail ×1/3、#06 根拠 fail→pass ×1/3、#06 範囲 pass→fail ×1/3、#08 分かりやすさ pass→fail ×1/3
- **model_flash**：#06 根拠 fail→pass ×1/1
- **rubric_grounding**：#06 根拠 fail→pass ×3/3、#08 根拠 fail→pass ×1/3
- **order_schema**：#06 根拠 fail→pass ×2/3
- **order_all**：#06 分かりやすさ pass→fail ×2/3、#06 根拠 fail→pass ×1/3、#08 分かりやすさ pass→fail ×1/3

## 返ってきた引数の順と、使ったトークン（1 件あたりの平均）

「理由が先」：各基準の引数で reason が verdict より先に書かれていた割合（4 基準 × 10 件 × run 数）。上位のキーの順は、schema の順（根拠・範囲・ヒント・分かりやすさ）どおりだった件数。

| 条件 | 理由が先 | 判定が先 | 上位のキーが schema の順 | 入力 tokens | 出力 tokens | thoughts tokens | 応答の数 |
|---|---|---|---|---|---|---|---|
| baseline | 61/120 | 59/120 | 3/30 | 1530 | 158 | 0 | 1.00 |
| model_flash | 17/40 | 23/40 | 1/10 | 1530 | 701 | 549 | 1.00 |
| rubric_grounding | 62/120 | 58/120 | 3/30 | 1587 | 156 | 0 | 1.00 |
| order_schema | 54/120 | 66/120 | 2/30 | 1530 | 156 | 0 | 1.00 |
| order_all | 65/120 | 55/120 | 0/30 | 1536 | 148 | 0 | 1.00 |
