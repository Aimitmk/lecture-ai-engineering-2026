# 第3回 解答

## 演習

- 第1回（素のLLM）とエージェントの回答の違い：
  - 同じ質問「AIE2026の講座の宿題にある「3レベル」とは何ですか？」を、両方に投げた（gemini-3.5-flash-lite、2026-11-15 11:56 JST）。ログは [素の LLM](results/exercise/ask_3levels.txt)・[エージェント](results/exercise/agent_3levels.txt)。
  - **素の LLM（`app.ask`）**：
    - 「初級・中級・上級」のような難易度別の3段階だと推測した。レベルごとの目的・内容・対象まで具体的に書いたが、どれも作り話。
    - 「自分のレベルに合わせてどれか一つ選んで提出する形式の場合もある」と、可能性の1つとしては挙げた。ただ、どれが本当かは示せず、Slack や講師に確認するよう勧めて終わった。
  - **エージェント（`app.agent`）**：
    - `search_glossary({'query': '3レベル'})` で用語集の「宿題の3レベル」を引いてから答えた。
    - 「基礎（講義内容の確認）・実装（自分でコードを書く）・発展（調査や試行）」「どれか1つで完了」「原則として採点しない」の3点が、`data/glossary.json` の `homework-levels` の定義と一致した。
    - 最後に「第1回」を付けた。
  - 宿題（基礎）の baseline で、同じ質問をさらに3回実行した。3回とも同じ検索をして、正しく答えた。
- `--trace` で見えたツール呼び出し（ツール名と引数）：
  - 「LoRAとQLoRAの違いは？」（[ログ](results/exercise/trace_lora_qlora.txt)）：
    - `search_glossary({'query': 'LoRA'})` と `search_glossary({'query': 'QLoRA'})` の2つ。
    - モデルは1回目の応答で2つを同時に依頼し、2回目の応答で答えた。
  - 「第2回の内容から確認問題を1問出して」（[ログ](results/exercise/trace_quiz.txt)）：`make_quiz({'lecture': 2})`。
- 1つの質問での LLM 呼び出し回数（`requests`）：
  - 3つの質問とも `requests=2` だった。内訳は、ツールを依頼する応答と、結果を見て答える応答。
  - LoRA と QLoRA は、2つの検索を1回の応答で同時に依頼したので、検索が2つあっても2回で済んだ。
  - 入力 / 出力トークンは、3レベル 985 / 141、LoRA・QLoRA 1,398 / 222、確認問題 924 / 60。入力には、指示とツールの説明が2回分（1回目と2回目の呼び出し）入る。
- 追加したツールと、docstring に書いた説明：
  - `app/tools.py` に `make_quiz(lecture: int) -> str` を作った。
    - 指定した回の用語を `random.choice` で1つ選ぶ。
    - `{"question": "「X」の意味は？", "answer": その用語の definition}` を JSON で返す。
    - 用語がない回（pytest の TestModel が呼ぶ `lecture=0` など）では、例外を出さずに「第0回の用語は用語集にありません。用語がある回: 第1回, 第2回, 第3回, 第5回」と返す。
  - docstring（モデルに見える説明文）：

    ```text
    指定した回（1始まりの整数）の用語から1つを選び、確認問題と答えを返す。

    「第2回の確認問題を出して」のように、復習用の問題を求められたときに使う。
    返り値は {"question": 問題, "answer": 答え} の JSON。
    ```

  - INSTRUCTIONS を変えなくても、`make_quiz({'lecture': 2})` で呼ばれた。
  - `--list-tools` に出ること（[ログ](results/exercise/list_tools.txt)）と、`uv run pytest -q` が 13 passed になること（[ログ](results/exercise/pytest.txt)）を確かめた。
  - テストを2つ足した。答えが、選ばれた用語の definition と一致すること。用語がない回でも落ちないこと。
  - **気づき：確認問題の答えを、モデルは毎回伏せた。**
    - 「考えてみたら、答えを確認してみてくださいね」のように書き、答えは出さなかった。
    - あとで同じ質問を Pydantic AI 版で3回、ADK 版で3回試し、演習の1回と合わせて計7回とも同じだった（下の「基礎」「発展 a」）。
    - ツールは答えも返しているが、`app.agent` は1回ごとに会話が終わる（履歴を持たない）。そのため、利用者があとから「答えは？」と聞いても、モデルはどの問題のことか分からない。
    - 復習に使うには、答えをいつ見せるかを決める必要がある。たとえば、INSTRUCTIONS に書くか、会話を続けられる CLI にする。
    - ADK 版の対話モードでは会話が続くので、2ターン目に答えを聞けた（発展 a）。

## 宿題

- 取り組んだレベル：**基礎・実装・発展 a**。発展 b は、システムプロンプトの比較まで（Pi を Codespaces で動かすのは、これから）
- 使ったモデル（`AIE_MODEL`）：
  - gemini-3.5-flash-lite（既定）。
  - 応答に記録されたモデル名も、すべて gemini-3.5-flash-lite だった（`runs.jsonl` の `model_name`、ADK の `modelVersion`）。
- 実行環境：
  - 発展 b 以外は、Codespaces ではなくローカルの macOS で実行した。Python 3.12.11、`uv sync --frozen` と同じ版（pydantic-ai-slim 2.57.0、google-genai 2.31.0）。
  - 発展 a の ADK は、`uv run --with google-adk` で入った google-adk 2.14.1 を使った（`pyproject.toml` と `uv.lock` は変えていない）。
  - API キーは git の管理外の `.env` に置き、`uv run --env-file .env` で渡した。
  - 実行日時は 2026-11-15 11:56〜12:13（JST）。
  - 発展 b の Pi だけは Codespaces で動かす（下の「発展 b」）。
- ブランチ：
  - fork の main が講座 repo より古く、第3回の問題文と `tests/test_agent.py` が更新されていた。
  - そのため、`lec03` は講座 repo の `lec03-start` タグから作った。
- AI ツール：
  - Claude Code（Claude Opus 5.5）が、次のことを行った：
    - コードの実装
    - 比較用スクリプトの作成
    - 実験の実行
    - 回答の読み取りと判定
    - この answer.md の下書き
  - 数値と回答の引用は、すべて `results/` のログの実測。
  - ユーザーが自分で確かめたこと：
    - answer.md や results/ のログ、PR #3 を、自分で開いて読んだ。
    - テスト（pytest）を自分で流し、エージェント（`app.agent` や `adk run`）を自分で動かした。
    - Claude の判定のうち 2 つを、Claude が Claude Code の画面に並べた抜粋（ログの文と Claude の見方）を読んで確かめた（2026-11-16）。どちらも Claude と同じ判断になった。
      - 実装の、断った回の最終回答：Claude と同じく、事実と違う説明だと判断した。断ったのは利用者なのに、「事前の確認が必要なため保留」では、確認がまだ済んでいないように読める。
      - 基礎の end_with_quiz で出た確認問題 6 問：Claude の分類（4/6 は直前の説明を聞き返すだけ、2/6 は回答で説明していない「ランク」を問う）は合っていると判断した。直前の説明を聞き返すだけの問題は、復習としては弱いと思う。

### 基礎：INSTRUCTIONS と docstring を1か所ずつ変えて、同じ質問で比べる

**やったこと**

- 1回に変えるのは1か所だけにした。条件は次の3通りと、何も変えない baseline。

  | 条件 | 変えたところ |
  |---|---|
  | baseline | 変えない（演習のまま） |
  | no_must_search | INSTRUCTIONS から「用語や講座に固有のことを答える前に、必ず search_glossary で用語集を確認する。」の行を消す |
  | docstring_batch | search_glossary の docstring の「query には調べたい用語を1つだけ入れる」を「まとめて入れる」にする |
  | end_with_quiz | INSTRUCTIONS の「回答の最後に、関係する回（第N回）を示す。」を「最後に確認問題を1問出す。」にする |

- 書き換え方：
  - app/ のファイルを書き換えて戻す代わりに、`scripts/lec03_prompt_variants.py` で `Agent.override(instructions=…)`・`Agent.override(tools=…)` を使い、モデルに渡す文だけを差し替えた。
  - 差し替えたあとの、モデルに渡る指示とツール定義を TestModel で取り出して保存した（`--dump`、[prompts/](results/basic/prompts/)）。
  - それを使って、baseline が agent.py のエージェントと同じであること、各条件の違いが1か所だけであることを確かめた（例：[docstring_batch.diff](results/basic/prompts/docstring_batch.diff)）。
- 実行：
  - 質問は「AIE2026の講座の宿題にある「3レベル」とは何ですか？」と「LoRAとQLoRAの違いは？」の2つ。
  - 各条件で3回ずつ、計24回。ほかに、baseline で確認問題の質問を3回（発展 a との比較用）。
  - 試行ごとに4条件を順番に回した。時間帯による混み具合の差が、特定の条件に偏らないようにするため。
  - 実行は 2026-11-15 11:58〜12:05 JST、commit `bbc8d50`（演習を終えた状態）。503 が1回出たが、再試行で成功した。
- 記録：
  - [runs.jsonl](results/basic/runs.jsonl)：1回1行。ツール呼び出し、requests、トークン、回答、`--trace` と同じ形式の trace。
  - 表は [summary.md](results/basic/summary.md)、回答の全文は [traces.md](results/basic/traces.md)。
- 判定：
  - 回答の中身（正しいか、最後に第N回があるか、確認問題があるか）は、27件すべてを読んで判定した。
  - 自動で判定したのは「最後の行に第N回があるか」だけ。

**結果**（gemini-3.5-flash-lite、各3回）

| 条件 | 3レベル：ツール呼び出し | LoRA・QLoRA：ツール呼び出し | requests | 入力 tokens（3レベル / LoRA） | 最後に第N回 | 回答の中身 |
|---|---|---|---:|---:|:---:|---|
| baseline | `'3レベル'` を1回（3/3） | `'LoRA'` と `'QLoRA'` の2回（3/3） | 2 | 985 / 1,398 | 6/6 | 6/6 正しい |
| no_must_search | 同じ（3/3） | 同じ（3/3） | 2 | 937 / 1,350 | 6/6 | 6/6 正しい |
| docstring_batch | 同じ（3/3） | **`'LoRA QLoRA'` の1回（3/3）** | 2 | 981 / **1,087** | 6/6 | 6/6 正しい |
| end_with_quiz | 同じ（3/3） | 同じ（3/3） | 2 | 971 / 1,384 | **0/6** | 6/6 正しい。6/6 で最後に**自作**の確認問題（make_quiz は 0/6） |

- **no_must_search（「必ず検索する」の行を消す）**：
  - 検索は減らなかった。6/6 で検索してから答えた。
  - search_glossary の docstring にも「AIエンジニアリングの用語や、この講座（AIE2026）に固有の言葉について答える前に使うこと」と書いてある。指示が2か所に重なっていたので、片方を消しても効かなかったのだと考えられる。
  - 入力トークンは48減った。消した1行の分（1回の呼び出しで24）が、2回の呼び出しで減った。
- **docstring_batch（「まとめて入れる」）**：
  - LoRA・QLoRA で、検索が2回から1回（`'LoRA QLoRA'`）になった（3/3）。
  - それでも requests は2のまま。baseline でも2つの検索を1回の応答で同時に依頼していたので、LLM を呼ぶ回数は変わらない。
  - 入力トークンは 1,398 → 1,087（−22%）に減った。search_glossary を直接呼んで、理由を確かめた：
    - baseline の `'LoRA'` は [LoRA, ランク（LoRAのr）, QLoRA] を、`'QLoRA'` は [QLoRA, LoRA] を返していた。LoRA と QLoRA が2回ずつ入っていた。
    - `'LoRA QLoRA'` は [LoRA, QLoRA] だけを返す。
  - まとめた検索で用語が欠けなかったのは、search_glossary の作りのおかげ。検索語から空白を取り除き、名前が検索語に含まれる用語も拾う。
    - 4語をまとめた `'LoRA QLoRA PEFT 量子化'` では [PEFT, LoRA, QLoRA] が返り、上限（`MAX_RESULTS = 3`）のために「量子化」が落ちた。
    - docstring の書き方だけでなく、ツールの作りがその書き方に合っているかが効く。
  - 3レベル（用語が1つ）では変わらなかった。
- **end_with_quiz（「第N回を示す」→「確認問題を1問出す」）**：
  - 6/6 で、回答の最後が確認問題になった。末尾の「第N回」は 0/6 になった。
  - 問題は、make_quiz を使わずにモデルが自分で作った（make_quiz の呼び出しは 0/6）。make_quiz の docstring は「復習用の問題を求められたときに使う」で、利用者は問題を求めていないからだと考えられる。
  - 問題の中身：
    - 4/6 は、直前の説明を聞き返すだけだった（例：「『基礎』『実装』と、あと1つは何でしょうか？」）。
    - 2/6 は、検索結果には入っていたが回答では説明していない「ランク（LoRAのr）」を問い、「用語集にヒントがあります」と添えた。利用者は用語集を見ていない。
    - 答えは6/6 で伏せた。
  - 「第N回を示す」の1行が、末尾の第N回をそのまま決めていた。この行を消すと、第N回は本文に紛れ込む程度になった（例：3回目の「第1回などで導入されている」）。

**気づき・疑問**

- 指示は INSTRUCTIONS と docstring の2か所にある。同じことが両方に書いてあると、片方を消しても動きは変わらない。どちらが効いているかを確かめるには、docstring の「答える前に使うこと」も消す条件が要る（今回は「1回に1か所」を守ったので、試していない）。
- docstring の文言で、引数の作り方（1語ずつか、まとめるか）は 3/3 で変わった。ただ、ツール側がその引数を受け止められる作りかどうかは、文言とは別に確かめる必要がある。
- `requests` は検索の回数ではなく、応答の往復の回数で決まる。同時に依頼できるなら、検索が増えても LLM の呼び出しは増えない。
- 疑問：今回の質問は、どちらも用語集にある語だった。用語集にない語（たとえば「RLHF」。用語集で「見つかりませんでした」になることは確かめた）を聞いたとき、no_must_search では検索せずに一般知識で答えるようになるのか。

### 実装：保存の前に利用者の確認を挟む save_learning_log

**やったこと**

- `app/tools.py` に `save_learning_log(title: str, content: str) -> str` を作った。
  - `learning_log/`（.gitignore 済み）の日付ごとのファイル（`learning_log/2026-11-15.md` など）に、`## 12:06 見出し` と本文を追記する。
  - 保存先のファイル名はモデルに決めさせず、ツールが作る。モデルが learning_log/ の外のパスを指定できないようにするため。
  - 見出しの改行は空白にし、空の見出し・本文は保存しない。
- `app/agent.py`：
  - `requires_approval=True` を付けて登録し、`output_type=[str, DeferredToolRequests]` にした。
- CLI（`main()`）：
  - 結果が `DeferredToolRequests` なら、`ask_approvals()` が `result.output.approvals` の呼び出しを1つずつ見せる。ツール名と引数（見出し・本文）を表示して、`[y/N]` を聞く。
  - y なら承認する。それ以外の答えと入力なし（EOF）は、`ToolDenied("利用者が保存を断ったので、保存していません。")` で断る。
  - その結果（`DeferredToolResults`）と会話（`message_history=result.all_messages()`）を渡して、もう一度 `run_sync` を呼ぶ。続きでまた承認待ちになることもあるので、`DeferredToolRequests` でなくなるまで繰り返す。
  - `usage=result.usage` も渡し、止まる前からの LLM の呼び出し回数を数え続ける。
  - `--list-tools` では、承認が必要なツールに「（実行の前に利用者の承認が必要）」と表示する（[ログ](results/impl/list_tools.txt)）。
- 使う場面は、INSTRUCTIONS ではなく docstring に書いた：
  - 「記録して」「保存して」と頼まれたときだけ使う。
  - 実行の前にプログラムが確認するので、呼ぶ前に聞き直さなくてよい。
  - INSTRUCTIONS は発展 a の ADK 版と共有しているので、ADK 版にないツールの名前を書きたくなかった。
- テスト（`tests/test_learning_log.py`、API キー不要、保存先は一時フォルダ）：
  - TestModel に save_learning_log を呼ばせて、次のことを確かめる：
    - 承認されるまで保存されない。
    - 承認すると保存される。
    - 断ると保存されず、断った理由がモデルに返る。
  - y・n・EOF の扱いも確かめる。
  - `uv run pytest` は 25 passed（[ログ](results/impl/pytest.txt)）。

**結果**

同じ依頼「LoRAとQLoRAの違いを調べて、要点を学習の記録に保存して」を2回実行した。ログは [承認する](results/impl/approve.txt)・[断る](results/impl/deny.txt)。

| | 承認する（y） | 断る（n） |
|---|---|---|
| ツール呼び出し | `search_glossary('LoRA')`・`('QLoRA')` → `save_learning_log(title='LoRAとQLoRAの違い', content=…)` | 同じ |
| 止まったところ | save_learning_log の呼び出し。引数を表示して y/N を聞いた | 同じ |
| ファイル | `learning_log/2026-11-15.md` ができた（480 バイト） | 変わらない（前後とも 480 バイトで、md5 も同じ） |
| モデルに返った戻り値 | 「learning_log/2026-11-15.md に保存しました（見出し: LoRAとQLoRAの違い）。」 | 「利用者が保存を断ったので、保存していません。」 |
| requests / tool_calls | 3 / 3 | 3 / 2 |
| 最終回答 | 「学習の記録に保存しました」と要点 | 要点と、「保存の実行にあたり事前の確認が必要なため、今回は保存を保留しています」 |

- LLM の呼び出しは3回だった：
  1. 検索を依頼する。
  2. 結果を見て save_learning_log を依頼する。ここで止まる。
  3. 承認の結果を見て答える。
- 断った回の tool_calls が2なのは、断った save_learning_log は実行されないので数えられないため。
- 保存された本文は、検索結果をモデルが要約したもの。用語集の定義と食い違うところはなかった。

**気づき・疑問**

- 承認の要否は、関数ではなく登録（`requires_approval=True`）で決まる。同じ関数を別の場所（ADK の `tools=[…]` など）にそのまま渡すと、確認なしで保存してしまう。そのため、発展 a では save_learning_log を ADK 版に入れなかった。
- 断ったときの説明が、事実と違っていた：
  - 戻り値は「利用者が保存を断った」なのに、モデルは「事前の確認が必要なため保留」と言い換えた。
  - 保存されていないことは正しく伝わった。
  - docstring の「実行の前にプログラムが利用者に確認する」に引っ張られたのかもしれない（1回だけの観察）。
  - 断ったことをそのまま伝えさせたいなら、戻り値か INSTRUCTIONS で指示する必要がありそう。
- 承認するかどうかは、モデルが作った引数（保存する本文）を読んで判断することになる。本文が長いと、確認の手間が増える。
- 疑問：承認待ちの状態（`DeferredToolRequests` と会話）を保存しておけば、別のプロセスや別の日に承認して、続きを実行できるのか。Web アプリで承認ボタンを押すような使い方。

### 発展 a：同じ指示とツールで、ADK に書き直す

**やったこと**

- 新しく作ったのは `adk_agent/glossary_agent/` の2ファイルだけ（app/ は変えていない）：
  - `__init__.py`：`from . import agent` の1行。
  - `agent.py`：`root_agent = Agent(model=MODEL, name="glossary_agent", instruction=INSTRUCTIONS, tools=[tools.search_glossary, tools.get_lecture_summary, tools.make_quiz])`
- model には `app.config.MODEL` を使い、Pydantic AI 版と同じモデルにそろえた（環境変数 `AIE_MODEL` で一緒に切り替わる）。
- save_learning_log は入れなかった（上の「実装」の気づき）。
- 実行：
  - problem.md の手順のコマンド（`PYTHONPATH=. uv run --with google-adk adk run adk_agent/glossary_agent`）に `--frozen --env-file .env` を足し、対話モードに質問をパイプで渡して1回動かした（[ログ](results/adk/interactive.txt)）。
  - 比較のため、`scripts/lec03_adk_compare.py` から `adk run --jsonl --in_memory` で、基礎の baseline と同じ3つの質問を3回ずつ投げた（12:09〜12:11 JST）。
  - JSONL には、モデルの応答（ツール呼び出しを含む）とツールの戻り値が、イベントとして1行ずつ出る（[runs/](results/adk/runs/)、回答の全文は [answers.md](results/adk/answers.md)）。
  - 対話モードで「確認問題を出して」→「答えを教えて」の2ターンも試した（[ログ](results/adk/interactive_quiz.txt)）。

**書き方の違い**

| | Pydantic AI 版（`app/agent.py`） | ADK 版（`adk_agent/glossary_agent/agent.py`） |
|---|---|---|
| 指示 | `Agent(instructions=INSTRUCTIONS)` | `Agent(instruction=INSTRUCTIONS)` |
| 指示の扱い | 渡した文がそのまま指示になる | 指示の文字列はテンプレートとして扱われ、`{名前}` にセッションの状態が埋め込まれる。いまの INSTRUCTIONS には `{}` がないので、そのまま渡る |
| フレームワークが足す指示 | なし | 「You are an agent. Your internal name is "glossary_agent".」を自動で足す（ADK のソース `flows/llm_flows/prompt/_identity.py` で確かめた） |
| ツール | 作ったあとで `agent.tool_plain(関数)` を1つずつ登録する。承認の要否などは登録のときに決める | 作るときに `tools=[関数, …]` でまとめて渡す。docstring と型ヒントが説明文になるのは同じ |
| モデル | 実行のときに渡す（`run_sync(…, model=…)`）。テストでは TestModel に差し替えられる | 作るときに決める（`model=…`） |
| 名前 | 要らない | `name` が必須 |
| 動かし方 | 自分で書いた CLI（`python -m app.agent`）。`--trace` も自作 | `adk run` が付いてくる（対話・単発の質問・`--jsonl`・`--replay`）。CLI がフォルダの `root_agent` を探して読み込むので、`__init__.py` で `agent` を import しておく |
| API キー | `uv run --env-file .env` で渡した | ADK は、agent のフォルダから上へたどって `.env` を自動で読み込んだ（ログに「Loaded .env file for glossary_agent at …/.env」と出た） |
| 会話 | 1回ごとに終わる | 対話モードでは会話が続く。既定では、agent のフォルダに `.adk/session.db` を作る（`.gitignore` に足した）。`--in_memory` を付けると作らない |
| ツール呼び出しの見え方 | `--trace`（自作。`result.all_messages()` から作る） | `--jsonl`（functionCall・functionResponse・回答のイベント） |

**回答の比べ方と結果**（各3回）

| 質問 | ツール呼び出し（両方とも） | LLM の呼び出し（PAI / ADK） | 入力 tokens（PAI / ADK） | 回答 |
|---|---|---:|---:|---|
| 3レベル | `search_glossary('3レベル')`（3/3） | 2 / 2 | 985 / 1,111 | 両方とも 3/3 正しく、最後に第1回 |
| LoRA・QLoRA | `search_glossary('LoRA')`・`('QLoRA')`（3/3） | 2 / 2 | 1,398 / 1,522 | 両方とも 3/3 正しく、最後に第2回 |
| 確認問題 | `make_quiz(lecture=2)`（3/3） | 2 / 2 | 918〜924 / 1,044〜1,053 | 両方とも 3/3 で問題だけを出し、答えは伏せた |

- ツールの選び方と引数は、9/9 で Pydantic AI 版と同じだった。指示とツールの説明文が同じなら、フレームワークを替えてもモデルのふるまいはほとんど変わらなかった。
- 入力トークンは、ADK 版のほうが毎回約125多かった（2回の呼び出しの合計）。
  - ADK が足す自己紹介の1文の分もあるが、それだけでは足りないように見える。ツール定義や戻り値の渡し方の違いも入っていると思われる（確かめていない）。
- 対話モードの2ターン（[ログ](results/adk/interactive_quiz.txt)）：
  - 1ターン目で「ファインチューニングの意味は？」を出し、2ターン目の「答えを教えて」に、用語集の定義どおりの答えを返した。
  - ADK のログでは、LLM の呼び出しは計3回（1ターン目に2回、2ターン目に1回）で、2ターン目はツールを呼ばずに会話の履歴から答えた。
  - Pydantic AI 版（1回ごとに終わる CLI）では、これができない。
- 確認問題の1回（ADK 版の3回目）では、「第2回『ニューラルネットワークの基礎』」と、回のタイトルを作り話で書いた。
  - make_quiz の戻り値（問題と答えだけ）にも、用語集にも、`data/lectures/02.md` にも、そのような語はない（第2回は「ファインチューニングとLoRA」）。
  - 「推測で断定しない」という指示があっても起きた。9回中1回で、Pydantic AI 版では起きていない。ただ、回数が少ないので、フレームワークの違いとは言えない。

**気づき・疑問**

- 書き直したのは「組み立てる部分」の約10行で、指示・ツール・モデルは同じまま動いた。違いが大きいのは周り（CLI、セッション、.env の読み込み、トレース）で、ADK はそれを最初から持っている。
- ADK は、フォルダから `.env` を自動で読み、`.adk/` に会話を保存する。便利だが、リポジトリの中に秘密情報や会話の記録ができる場所が増える。`.gitignore` を確かめる必要がある。
- 疑問：入力トークンの差（約125）の内訳。ADK と Pydantic AI で、ツール定義と戻り値をどう Gemini に渡しているかを、リクエストで比べてみたい。

### 発展 b：Pi のシステムプロンプトと、自分の INSTRUCTIONS を比べる

**やったこと**

- Pi の公開リポジトリ（[earendil-works/pi](https://github.com/earendil-works/pi)、MIT License）から、次のファイルを読んだ。npm の最新版 1.5.2 と同じタグ `v1.5.2`（commit `b4afddd`）のもの。
  - `packages/coding-agent/src/core/system-prompt.ts`
  - 組み込みツール（read・bash・edit・write）の定義
- 既定の設定で組み立てられるシステムプロンプトを書き出した（[system_prompt_v1.5.2.md](results/pi/system_prompt_v1.5.2.md)）。
- Codespaces で Pi を動かした結果：（実行待ち）

**比較**

| 観点 | Pi のシステムプロンプト | 自分の INSTRUCTIONS |
|---|---|---|
| 役割 | 「pi というハーネスの中で動くコーディングアシスタント。ファイルを調べ、コマンドを実行し、コードを直すのを手伝う」 | 「AIE2026 の学習支援エージェント」 |
| ツールの一覧 | `<tools>` に4つを1行ずつ（read: Read file contents など）。「Additional tools may be available.」 | 書いていない。ツールの説明は docstring 側（ツール定義）にある |
| ツールのルール | 正しく使うためのルール。「cat や sed ではなく read で読む」「edit の oldText は元のファイルと一意に一致させる」「write は新しいファイルか全体の書き直しにだけ使う」 | 使う場面のルール。「答える前に必ず search_glossary」「回の内容は get_lecture_summary」 |
| 答え方 | 「簡潔に」「ファイルのパスをはっきり示す」 | 「最後に第N回を示す」「宿題の答えは書かず、ヒントで導く」 |
| 分からないとき | 書いていない | 「用語集にないことは、推測で断定せず『用語集にはない』と伝える」 |
| プロジェクト固有の知識 | プロンプト本体には持たない。作業ディレクトリから上へたどって見つけた AGENTS.md・CLAUDE.md などを `<project_context>` として足す | 講座固有のルールを INSTRUCTIONS に直接書いている |
| 環境の情報 | `<cwd>` に作業ディレクトリ。`<docs>` に Pi 自身のドキュメントの場所（ハーネスについて聞かれたときだけ読む） | 書いていない |
| 安全・確認 | 書いていない。Pi は確認を求めずに実行する。公式ドキュメント（docs/security.md）は、コンテナやサンドボックスの中で動かすことを勧めている | 書いていない。確認はプロンプトではなく、プログラム側（実装の `requires_approval`）で挟んだ |
| 組み立て方 | 選んだツールや見つけたファイルから、セクション（preamble・tools・rules・docs・project_context・skills・cwd）を組み立てる。会話の途中で変わったセクションだけを送り直す仕組みもある | 固定の文字列 |

**気づき・疑問**

- 書き分けが逆になっている：
  - Pi は「何をする人か」と「道具の正しい使い方」だけを書き、プロジェクトで何を守るべきかは AGENTS.md に任せている。
  - 自分の INSTRUCTIONS は、道具の説明を docstring に任せ、領域のルール（検索してから答える、推測しない、答えを書かない）を書いている。
- どちらも、安全のための確認をプロンプトには書いていない。Pi は環境（Codespaces・コンテナ）で守り、自分のエージェントは承認の仕組み（実装）で守っている。「確認してから実行して」とプロンプトに書くより、プログラムで止めるほうが確実だと思う。基礎で見たとおり、プロンプトの1行は効いたり効かなかったりする。
- Pi の rules は、ツールを選ぶと、そのツールの guideline が足される作り。自分のエージェントでも、ツールを足すたびに INSTRUCTIONS を書き足すのではなく、ツールの側に「使い方の1行」を持たせる形にできる。基礎で見た「docstring にも同じことが書いてある」は、その形に近い。
- 疑問：Pi に講座固有のルールを守らせたいときは、AGENTS.md に何を書けば、自分の INSTRUCTIONS と同じふるまいになるのか。
