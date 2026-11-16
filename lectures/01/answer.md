# 第1回 解答

## 演習

- 講座に固有の質問（宿題の3レベル）へのモデルの回答（要約でよい）：
  gemini-3.5-flash-lite は、AIE2026 を「AIエンジニア育成講座などの2026年目標のプログラムを想定」と推測した。そのうえで「レベル1：基礎・初級／レベル2：応用・中級／レベル3：発展・上級」という難易度別の3段階を、目的・内容・対象つきで説明した。最後に「講座の Slack や講師に確認を」と添えていた（[ログ](results/exercise_ask.txt)）。
- 用語集の正しい意味と比べて気づいたこと：
  - 用語集（`data/glossary.json` の `homework-levels`）では、宿題は「基礎（講義内容の確認）・実装（自分でコードを書く）・発展（調査や試行）」の3段階で、**どれか1つに取り組めば完了**、**原則として採点はしない**。
  - モデルの答えは「基礎」「発展」という語こそ合っていたが、「実装」が「応用」になっていた。「どれか1つで完了」「採点しない」という肝心のルールはまったく出てこなかった。
  - 「一般的には」と前置きしながら、各レベルの目的・内容・対象まで具体的に書くので、知らずに読むと信じてしまいそうな答えだった。
  - 宿題で同じ質問を3モデル・temperature 3通りで計 16 回成功させたが、正しい答えは一度も出なかった（下の「基礎」）。
  - 1回だけ、並べた3つの解釈の1つに「3つのコースから選んで提出する形式」が入っていた。ただ同じところで「レベル1は全員必須」とも書いていたので、どれが本当かは答えからは判断できない。
- 表示できたトークン数（入力 / 出力）：
  - 既定の質問：**入力 21 / 出力 607**（思考 0、合計 628）
  - 「LoRAとは何ですか？」：**入力 7 / 出力 717**（思考 0、合計 724）
  - どちらも gemini-3.5-flash-lite（2026-10-22 19:52 JST）。

## 宿題

- 取り組んだレベル：**基礎・実装・発展（すべて）**
- 使ったモデル（`AIE_MODEL`）：
  - gemini-3.5-flash-lite（既定）、gemini-3.1-flash-lite、gemini-3.8-flash。
  - 計測した呼び出し（`runs.jsonl`）では、応答の `model_version` はすべて指定したモデル名と同じだった。別のモデルに振り替えられた呼び出しはなかった。
- 実行環境：
  - Codespaces ではなく、ローカルの macOS で実行した（Python 3.12.11、google-genai 2.31.0、`uv sync --frozen`）。
  - API キーは git の管理外の `.env` に置き、`uv run --env-file .env` で渡した。
  - 実行日時は 2026-10-22 19:52〜20:19（JST）。
  - Codespaces とはネットワークの経路が違うので、応答時間の絶対値はそのまま比べられない。
- 記録：
  - 計測した呼び出しは [`results/runs.jsonl`](results/runs.jsonl) に1回1行で残した（回答の本文、応答時間、トークン数、エラーの中身）。
  - 下の表は `uv run python -m scripts.measure_ask --summary` で作った。
- AI ツール：
  - Claude Code（Claude Opus 5.5）を使い、コードの実装、計測スクリプトの作成、実験の実行、この answer.md の下書きを行った。
  - 数値はすべて上の実行ログの実測。コードの差分と実行ログは自分で読んで確認した。

### 基礎：同じ質問を3回ずつ、モデルと temperature を変えて比べる

**やったこと**

- 3種類の質問を、モデルごとに3回ずつ送った（`scripts/measure_ask.py`）。
  - short：「日本の首都はどこですか？一言で答えてください。」
  - general：「LoRAとは何ですか？」
  - course：「AIE2026の講座の宿題にある「3レベル」とは何ですか？」
- gemini-3.8-flash は上位モデルで無料枠の上限が小さい可能性があるので、回数を絞り、general と course だけにした。
- temperature は、`app/ask.py` に `--temperature` を足して `types.GenerateContentConfig(temperature=…)` を渡せるようにした。gemini-3.5-flash-lite の course を、T = 0.0 / 1.0 / 2.0 で3回ずつ送った。
  - API のモデル一覧（[`results/models.md`](results/models.md)）では、3モデルとも temperature の既定値は 1.0、最大は 2.0。
- 503 で失敗したところは、あとで1回だけ再実行した。そのため「成功/回数」の回数には失敗した分も入っている。

**結果**

| モデル | 質問 | 成功/回数 | 3回の回答の違い | 類似度※ |
|---|---|---|---|---:|
| gemini-3.5-flash-lite | short | 3/3 | 「東京」が1回、「東京です。」が2回 | 0.71 |
| gemini-3.5-flash-lite | general | 3/3 | 趣旨は同じ。構成・たとえ・長さ（985〜1514 文字）が毎回違う | 0.30 |
| gemini-3.5-flash-lite | course | 3/3 | 2回は「基礎／応用／発展・挑戦」、1回は3通りの解釈（習得度・AIとの協働・複雑さ）を並べた。どれも作り話 | 0.19 |
| gemini-3.1-flash-lite | short | 3/4 | 3回とも「東京です。」 | 1.00 |
| gemini-3.1-flash-lite | general | 2/4 | 趣旨は同じ。長さもほぼ同じ（1441〜1456 文字） | 0.39 |
| gemini-3.1-flash-lite | course | 2/4 | 「難易度別・抽象度別」と「AIアシスタント→AIエージェント」で、解釈からして違う | 0.08 |
| gemini-3.8-flash | general | 2/4 | 趣旨も章立て（背景・仕組み・メリット・使われ方）もほぼ同じ | 0.40 |
| gemini-3.8-flash | course | 2/4 | 2回とも「基礎・必須達成／応用・標準／発展・挑戦」の評価基準という、同じ作り話 | 0.33 |
| gemini-3.5-flash-lite（T=0.0） | course | 3/3 | 3回とも違う作り話。書き出しの言い回しは似ている | 0.25 |
| gemini-3.5-flash-lite（T=1.0） | course | 3/3 | 構成の違いが大きくなった（「ブルームのタキソノミー」を持ち出した回もある） | 0.15 |
| gemini-3.5-flash-lite（T=2.0） | course | 3/3 | 「AI活用の習得レベル」「プロンプトの深化」など、解釈が広がった。文章は崩れない | 0.10 |

※ 類似度は、回答どうしを `difflib.SequenceMatcher` で比べた比率の平均。1.0 なら一字一句同じ。文字単位のおおまかな目安。

- **short**：どのモデルも「東京」か「東京です。」で、ほとんど揺れなかった。
- **general（LoRA）**：
  - 3モデルとも内容はおおむね正しかった（小さな低ランク行列を足して学習し、元の重みは固定する、など）。
  - ただし構成・たとえ・長さは毎回変わった（3.5-flash-lite で 985〜1514 文字）。
- **course**：すべてのモデル・すべての回で、一般論として「もっともらしい3段階」を答えた。正解（基礎・実装・発展、どれか1つで完了）は一度も出なかった。モデルごとの違い：
  - **3.5-flash-lite**：「基礎／応用／発展・挑戦」型が中心だった。1回は「手元でカリキュラムを参照しているわけではない」と断ったうえで、複数の解釈を並べた。
  - **3.1-flash-lite**：1回目は「難易度別」と「抽象度別（概念・ロジック・実装）」の2案だった。2回目は「AIアシスタント → AIパートナー → AIエージェント」という、まったく別の解釈だった（類似度 0.08）。
  - **3.8-flash**：1回目は「松尾研関連の講座」と当たりをつけた。2回とも「レベル1：基礎・必須達成（パス基準）／レベル2：応用・標準（推奨目標）／レベル3：発展・挑戦（高評価）」と、評価基準として具体的に説明した。回答どうしはほかのモデルより揃っていた（類似度 0.33）。実際は「どれか1つで完了・原則採点なし」なので、揃って、しかも詳しく間違えていた。
- **temperature**：
  - T = 0 / 1 / 2 のどれもエラーにならず、どの温度でも3回の回答はすべて違った。
  - 類似度は T=0 が 0.25、T=1 が 0.15、T=2 が 0.10 で、温度を上げるほど回答がばらつく方向には動いた。
  - ただし T=0 でも同じ答えにはならず、T=2 でも文章が崩れることはなかった。3回ずつなので、効き方の大きさまでは言えない。
  - どの温度でも、中身は作り話のままだった。**温度を下げても正しくはならない**（安定するかどうかと、正しいかどうかは別のこと）。

### 実装：会話履歴を保ったまま続けて質問する

**やったこと**

- `app/ask.py` に `--chat` を追加した（`uv run python -m app.ask --chat`）。
  - `client.chats.create()` で会話のセッションを作る。`send_message()` で質問するたびに、それまでの質問と回答（履歴）をまとめて送り直す。
  - 空行・`exit`・Ctrl+D で終了する。
  - 毎ターン、トークン数と履歴の件数を表示する。
  - API エラーが出たターンは履歴に入れずに、次の質問を受け付ける。
- 3ターンの質問をパイプで渡して実行した。対照として、履歴なしの1回だけの質問も試した。

**結果**（gemini-3.5-flash-lite、[ログ](results/chat_demo.txt)）

| ターン | 質問 | 入力 | 出力 | 履歴 | 回答 |
|---|---|---:|---:|---:|---|
| 1 | LoRAとは何ですか？3行で答えてください。 | 14 | 98 | 2 件 | 3行で説明した |
| 2 | それをQLoRAと比べると？ | 122 | 144 | 4 件 | 「それ」を LoRA と理解して比較した。1ターン目の「3行で」も引き継いだ |
| 3 | 私が最初に聞いた質問は何でしたか？ | 276 | 24 | 6 件 | 「LoRAとは何ですか？3行で答えてください。」と正しく答えた |

- 入力トークンは 14 → 122 → 276 と増えた。
  - 2ターン目の 122 ≒ 1ターン目の入力 14 ＋ 出力 98 ＋ 新しい質問。
  - 3ターン目の 276 ≒ 122 ＋ 144 ＋ 新しい質問。
  - **API は会話を覚えておらず、履歴を毎回送り直している**ことが、数字で確かめられた。
- 対照：履歴なしの `app.ask "それをQLoRAと比べると？"` では、「『それ』が明示されていない」と返して、何と比べるかを聞き返してきた（入力 9 トークン）。

### 発展：応答時間とトークン数を計測し、レート制限との関係を考える

**やったこと**

- `scripts/measure_ask.py` を作った。1回呼ぶごとに、次のものを JSONL に追記する。
  - `generate_content` の前後を `time.perf_counter()` ではさんで測った応答時間
  - `usage_metadata` の入力・出力・思考・合計トークン
  - `model_version`、回答の本文
  - エラーの中身（429 なら `quotaId`・`quotaValue`・`retryDelay`）
- google-genai は既定では自動で再試行しないので、応答時間は1回の呼び出しにかかった時間になる。
- 呼び出しの間隔は、flash-lite 系が 5 秒、3.8-flash が 15 秒。429 が出たらそこで止めた。
- レート制限を確かめるため、gemini-3.5-flash-lite に short を間隔なしで最大 20 回送り、最初の 429 で止めた。これを2回行った。

**結果：モデル・質問ごとの応答時間とトークン数**（平均。応答時間のかっこ内は最小〜最大）

| モデル | 質問 | 成功/回数 | 応答時間（秒） | 入力 | 出力 | 思考 | 合計 | (出力+思考)/秒 |
|---|---|---|---|---:|---:|---:|---:|---:|
| gemini-3.5-flash-lite | short | 3/3 | 0.69（0.60〜0.81） | 14 | 2 | 0 | 16 | 3 |
| gemini-3.5-flash-lite | general | 3/3 | 2.96（2.55〜3.55） | 7 | 601 | 0 | 608 | 203 |
| gemini-3.5-flash-lite | course | 3/3 | 3.32（2.87〜4.07） | 21 | 650 | 0 | 671 | 196 |
| gemini-3.1-flash-lite | short | 3/4 | 13.13（3.05〜24.01） | 14 | 3 | 0 | 17 | 0 |
| gemini-3.1-flash-lite | general | 2/4 | 7.53（6.71〜8.36） | 7 | 742 | 0 | 750 | 99 |
| gemini-3.1-flash-lite | course | 2/4 | 43.82（18.96〜68.68） | 21 | 686 | 0 | 707 | 16 |
| gemini-3.8-flash | general | 2/4 | 324.95（296.64〜353.26） | 7 | 820 | 931 | 1758 | 5 |
| gemini-3.8-flash | course | 2/4 | 287.87（287.37〜288.38） | 21 | 660 | 1220 | 1901 | 7 |

応答時間と（出力＋思考）トークン数に、直線を当てはめた結果：

- gemini-3.5-flash-lite：応答時間 ≈ 0.66 秒 ＋ 4.0 ミリ秒 × トークン数（相関係数 0.99、9 点）。1 トークンあたり 4 ミリ秒は、毎秒約 250 トークンにあたる。
- gemini-3.1-flash-lite：相関係数 0.27（7 点）。3 トークンの回答に 24 秒かかった回もあり、トークン数では説明できない。
- gemini-3.8-flash：相関係数 0.03（4 点）。4 回とも 287〜353 秒かかり、トークン数（約 1,650〜1,900）とはほぼ無関係だった。

**結果：エラー**

- gemini-3.5-flash-lite：計測した 53 回のうち、エラーは連続呼び出しの最後の 429 が 2 回だけだった。503 は 0 回。
- gemini-3.1-flash-lite：12 回中 5 回が 503 だった（再実行した 3 回のうち 2 回も 503）。
- gemini-3.8-flash：8 回中 4 回が 503 だった（再実行した 2 回とも 503）。
- 503 は 1〜25 秒で返ってきた。本文は「This model is currently experiencing high demand. Spikes in demand are usually temporary.」。

**結果：間隔なしの連続呼び出し（gemini-3.5-flash-lite、short）**

| 回 | 開始 | その前の状況 | 最初の 429 までの成功 | 429 までの時間 | 429 の retryDelay |
|---|---|---|---:|---:|---|
| 1 | 20:09:55 | 約30秒前まで、実装のデモで4回呼んでいた | 14 回 | 10.3 秒 | 53s |
| 2 | 20:13:01 | 3分ほど呼び出しなし | 19 回 | 13.1 秒 | 45s |

429 の本文には、`quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier`、`quotaValue: 15` と書かれていた。

<details>
<summary>集計の全体（<code>--summary</code> の出力）</summary>

**モデル・質問ごとの集計**

| tag | モデル | temperature | 質問 | 成功/回数 | 応答時間 平均（最小〜最大）秒 | 入力 | 出力 | 思考 | 合計 | (出力+思考)/秒 | 異なる回答 | 類似度 | 回答の文字数 | model_version |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| models | gemini-3.5-flash-lite | 既定 | short | 3/3 | 0.69（0.60〜0.81） | 14 | 2 | 0 | 16 | 3 | 2 | 0.71 | 2〜5 | gemini-3.5-flash-lite |
| models | gemini-3.5-flash-lite | 既定 | general | 3/3 | 2.96（2.55〜3.55） | 7 | 601 | 0 | 608 | 203 | 3 | 0.30 | 985〜1514 | gemini-3.5-flash-lite |
| models | gemini-3.5-flash-lite | 既定 | course | 3/3 | 3.32（2.87〜4.07） | 21 | 650 | 0 | 671 | 196 | 3 | 0.19 | 1121〜1390 | gemini-3.5-flash-lite |
| models | gemini-3.1-flash-lite | 既定 | short | 3/4 | 13.13（3.05〜24.01） | 14 | 3 | 0 | 17 | 0 | 1 | 1.00 | 5〜5 | gemini-3.1-flash-lite |
| models | gemini-3.1-flash-lite | 既定 | general | 2/4 | 7.53（6.71〜8.36） | 7 | 742 | 0 | 750 | 99 | 2 | 0.39 | 1441〜1456 | gemini-3.1-flash-lite |
| models | gemini-3.1-flash-lite | 既定 | course | 2/4 | 43.82（18.96〜68.68） | 21 | 686 | 0 | 707 | 16 | 2 | 0.08 | 1255〜1298 | gemini-3.1-flash-lite |
| models | gemini-3.8-flash | 既定 | general | 2/4 | 324.95（296.64〜353.26） | 7 | 820 | 931 | 1758 | 5 | 2 | 0.40 | 1446〜1679 | gemini-3.8-flash |
| models | gemini-3.8-flash | 既定 | course | 2/4 | 287.87（287.37〜288.38） | 21 | 660 | 1220 | 1901 | 7 | 2 | 0.33 | 1223〜1279 | gemini-3.8-flash |
| temperature | gemini-3.5-flash-lite | 0.0 | course | 3/3 | 2.89（2.72〜3.06） | 21 | 527 | 0 | 548 | 182 | 3 | 0.25 | 932〜1003 | gemini-3.5-flash-lite |
| temperature | gemini-3.5-flash-lite | 1.0 | course | 3/3 | 3.14（2.46〜3.64） | 21 | 553 | 0 | 574 | 176 | 3 | 0.15 | 796〜1369 | gemini-3.5-flash-lite |
| temperature | gemini-3.5-flash-lite | 2.0 | course | 3/3 | 3.00（2.57〜3.85） | 21 | 573 | 0 | 594 | 191 | 3 | 0.10 | 778〜1426 | gemini-3.5-flash-lite |

**応答時間と（出力+思考）トークン数の関係（tag=models）**

- gemini-3.5-flash-lite: 応答時間 ≈ 0.66 秒 + 4.0 ミリ秒 × トークン数（相関係数 0.99、9 点）
- gemini-3.1-flash-lite: 応答時間 ≈ 13.73 秒 + 16.0 ミリ秒 × トークン数（相関係数 0.27、7 点）
- gemini-3.8-flash: 応答時間 ≈ 288.39 秒 + 9.9 ミリ秒 × トークン数（相関係数 0.03、4 点）

**エラー**

| 時刻 | tag | モデル | 質問 | 回 | code | status | quota（id = 上限） | retry_delay | message |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-22T19:54:05+09:00 | models | gemini-3.1-flash-lite | general | 1 | 503 | UNAVAILABLE |  |  | This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later. |
| 2026-10-22T19:56:18+09:00 | models | gemini-3.1-flash-lite | short | 3 | 503 | UNAVAILABLE |  |  | This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later. |
| 2026-10-22T19:56:38+09:00 | models | gemini-3.1-flash-lite | course | 3 | 503 | UNAVAILABLE |  |  | This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later. |
| 2026-10-22T19:56:57+09:00 | models | gemini-3.8-flash | general | 1 | 503 | UNAVAILABLE |  |  | This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later. |
| 2026-10-22T20:08:26+09:00 | models | gemini-3.8-flash | course | 2 | 503 | UNAVAILABLE |  |  | This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later. |
| 2026-10-22T20:10:05+09:00 | burst | gemini-3.5-flash-lite | short | 15 | 429 | RESOURCE_EXHAUSTED | GenerateRequestsPerMinutePerProjectPerModel-FreeTier = 15 | 53s | You exceeded your current quota, please check your plan and billing details. For more information on this error, head to |
| 2026-10-22T20:10:52+09:00 | models | gemini-3.1-flash-lite | general | 1 | 503 | UNAVAILABLE |  |  | This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later. |
| 2026-10-22T20:11:51+09:00 | models | gemini-3.1-flash-lite | course | 1 | 503 | UNAVAILABLE |  |  | This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later. |
| 2026-10-22T20:13:14+09:00 | burst | gemini-3.5-flash-lite | short | 20 | 429 | RESOURCE_EXHAUSTED | GenerateRequestsPerMinutePerProjectPerModel-FreeTier = 15 | 45s | You exceeded your current quota, please check your plan and billing details. For more information on this error, head to |
| 2026-10-22T20:18:50+09:00 | models | gemini-3.8-flash | general | 1 | 503 | UNAVAILABLE |  |  | This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later. |
| 2026-10-22T20:19:16+09:00 | models | gemini-3.8-flash | course | 1 | 503 | UNAVAILABLE |  |  | This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later. |

**間隔なしの連続呼び出し（tag=burst）**

| 開始 | モデル | 呼び出し | 最初の 429 までの成功 | 最初の 429 の時刻（開始からの秒） | 成功の応答時間 平均 秒 |
|---|---|---:|---:|---:|---:|
| 2026-10-22T20:09:55+09:00 | gemini-3.5-flash-lite | 15 | 14 | 10.296 | 0.73 |
| 2026-10-22T20:13:01+09:00 | gemini-3.5-flash-lite | 20 | 19 | 13.126 | 0.69 |

</details>

**考察：レート制限との関係**

1. **上限の正体**：429 の本文から、gemini-3.5-flash-lite の無料枠は「プロジェクト・モデルごとに、1分 15 リクエスト」だと分かった。数えているのはトークン数ではなく、リクエストの数。ほかの2モデルは 429 に当たらなかったので、上限の値は確かめていない。
2. **応答が速いほど、上限に当たりやすい**：
   - flash-lite の short は 0.7 秒ほどで返る。間隔なしで回すと1分 80 回を超える速さになり、10〜13 秒で 429 になった。
   - 長い回答（約 3 秒）でも、間隔なしなら1分 20 回になって上限を超える。
   - 15/分を守るには、1回ごとに 4 秒以上空ける必要がある。5 秒空けた計測では、429 は一度も出なかった。
3. **上限は「ぴったり 15 回」ではなかった**：
   - 1回目は 14 回、2回目は 19 回成功してから 429 になった。
   - retryDelay は 53 秒と 45 秒。どちらも、429 を受けた時刻から次の「分」の変わり目（20:11:00、20:14:00）までの時間とほぼ一致した。
   - 数え方は公開されていないので推測だが、「直近 60 秒にちょうど 15 回」を厳密に数えているわけではなさそう。
   - 上限まで使い切る前提にはしないほうがよい。余裕を持ったペースで送り、429 を受けたら retryDelay だけ待つ作りにすべきだと思った。
4. **503 は 429 とは別物**：
   - 503 は「モデルが混み合っている」というサーバー側の都合で、自分の上限とは関係なく起きる。
   - この時間帯は、3.1-flash-lite で 12 回中 5 回、3.8-flash で 8 回中 4 回が 503 だった。
   - README には、503 が続くときは 3.1-flash-lite を試すようにとあるが、今回はそちらも混んでいた。
   - 503 は、少し待って再実行するか、別のモデルに切り替えるしかない。
5. **応答時間は、トークン数だけでは決まらない**：
   - flash-lite は「固定で約 0.7 秒 ＋ 1 トークンあたり約 4 ミリ秒（毎秒 250 トークンほど）」で、ほぼ説明できた。
   - 混んでいた 3.1-flash-lite と 3.8-flash は待ち時間が大半を占め、トークン数との相関は弱かった。
   - 3.8-flash は1回 5〜6 分（287〜353 秒）かかり、（出力＋思考）トークンにすると毎秒 5〜7 トークンにしかならない。同じ時刻に flash-lite は毎秒 200 トークン近く出ていたので、手元の回線ではなく、サーバー側で待たされていたと考えられる。
6. **思考トークン**：
   - 3.8-flash は、4回とも回答本文（出力 646〜872）より多い思考トークン（892〜1232）を使っていた。思考は本文には出ないが、合計トークンに含まれ、時間もかかる。
   - flash-lite 系の思考は 0 だった。モデル一覧では thinking に対応しているが、既定では思考していない。
   - 「出力トークン」だけを見ると、実際の負荷を半分以下に見積もってしまう。
7. **1日あたりの上限と、実験の組み立て方**：
   - 今回当たった 429 は、すべて「1分あたり」の上限だった。1日あたりの上限には当たっていない（flash-lite は計 59 回）。
   - 1日の上限が小さいかもしれないモデルや、遅いモデルは回数を絞った。繰り返しの多い計測は lite モデルで行った。
8. **会話やエージェントでは、消費がもっと増える**：
   - 実装の `--chat` では、ターンごとに、それまでの会話の分だけ入力トークンが増えた（14 → 122 → 276）。
   - N ターン続けると、送るトークンの合計は N の2乗に近い速さで増える。そうなると、1分あたりのトークン数の上限や、コンテキストウィンドウ（今回のモデルは入力 1,048,576 トークン）に効いてくる。
   - 第3回のエージェントは、1つの質問で LLM を何回も呼ぶ。15/分の枠だと、1分に答えられる質問は「15 ÷ 1問あたりの呼び出し回数」に減る。

### 気づき・疑問

- 素の LLM は、講座に固有のことを知らないのに、毎回違う「もっともらしい構成」を自信を持って作る。上位モデル（3.8-flash）ほど詳しく書くぶん、間違いも具体的になった。温度を下げても正しくはならないので、第3回のように用語集を引かせる仕組みが必要だと実感した。
- 応答時間はモデルの大きさよりも、そのときの混み具合に強く左右された。flash-lite は数秒で安定していたが、3.8-flash は1回 5〜6 分、3.1-flash-lite も最大 69 秒かかったうえ、503 も多かった。
- 思考トークンは画面に出ないが、3.8-flash では回答本文より多く使っていた。費用や時間を見積もるときは、出力ではなく合計で見るべきだと分かった。
- レート制限は「15/分」と書かれていても、実際に止められる回数は 14 回や 19 回とぶれた。上限ぎりぎりまで使う作りにはせず、ペース配分と 429 のときの待機（retryDelay を読む）を入れるべきだと思った。
- 疑問：
  - T=0 でも回答が変わるのはなぜか（サーバー側の非決定性なのか）。`seed` を指定すれば同じ回答になるか。
  - 3.8-flash の待ち時間は、ストリーミングにしたら最初のトークンが出るまでの時間がどうなるか。混雑と思考の時間を分けて測りたい。
  - 503 が多い時間帯に傾向はあるのか。有料枠なら待ち時間は変わるのか。
