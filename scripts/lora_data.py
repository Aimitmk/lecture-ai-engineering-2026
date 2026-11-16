"""第2回 宿題: LoRA の学習と評価に使うデータ。

- COURSE: 講座 FAQ。notebooks/lora_format_tuning.ipynb のセクション 2・3・6 の値をそのまま写したもの
  （tests/test_lora_data.py で、ノートブックのセルと一致することを確かめる）。
- CRYPTO: 実装で使う、架空の暗号資産取引所の FAQ。数値はすべて架空で、実在の取引所とは関係ない。
- GLOSSARY_EVAL: 発展で使う、用語集についての評価用の質問と正解。

標準ライブラリだけを使うので、講座の uv 環境（torch なし）でも読み込める。
"""

import json
import re
import unicodedata

# ---- 講座 FAQ（ノートブックから写したもの。値を変えない） ----

COURSE = {
    "system": "あなたは講座 FAQ の回答係です。与えられた FAQ だけを根拠に、必ず JSON 1 行で答えてください。形式: {\"answer\": 文字列, \"needs_review\": 真偽値}。FAQ に記載が無いことは answer に『確認が必要』と書き、needs_review を true にします。",
    "faq": {
        "deadline": "課題の提出期限は 9 月 30 日 23:59（日本時間）です。",
        "destination": "提出先は学習ポータルの「課題」欄です。",
        "format": "提出形式は PDF 1 ファイルで、ファイル名は 学籍番号_課題番号.pdf です。",
        "office_hours": "質問は毎週火曜 17:00〜18:00 のオフィスアワーで受け付けます。",
        "late": "期限後の提出は、期限から 48 時間以内なら減点のうえ受け付けます。",
    },
    # 根拠あり: (質問テンプレート群, 正解の answer に含まれるべき語)
    "grounded": {
        "deadline": (["課題の提出期限はいつですか", "いつまでに出せばいいですか", "締切を教えてください", "提出の期限は？"], ["9 月 30 日", "23:59"]),
        "destination": (["提出先はどこですか", "どこにアップロードしますか", "課題はどこから出しますか", "提出場所は？"], ["学習ポータル", "課題"]),
        "format": (["提出形式を教えてください", "ファイル名の決まりはありますか", "何のファイル形式で出しますか", "PDF 以外でも出せますか"], ["PDF"]),
        "office_hours": (["質問はいつできますか", "オフィスアワーはいつですか", "先生に質問する時間はありますか", "相談できる時間帯は？"], ["火曜", "17:00"]),
        "late": (["遅れて出したらどうなりますか", "期限を過ぎた場合は受け付けますか", "遅延提出のルールは？", "締切後の扱いを教えてください"], ["48 時間", "減点"]),
    },
    # 根拠なし: FAQ に無いので needs_review=true が正解
    "ungrounded": [
        "再提出はできますか", "欠席した回の扱いを教えてください", "他の受講者の点数は見られますか",
        "成績はいつ出ますか", "提出期限は延長できますか", "グループでの提出は可能ですか",
        "課題の配点はどうなっていますか", "講義の録画は公開されますか",
    ],
    # test 専用の追加質問（train / valid には入れない）
    "test_extra_grounded": {
        "deadline": ["提出期限の日付と時刻を教えてください", "課題の締切は何月何日の何時ですか"],
        "destination": ["課題の提出はどこで行いますか", "提出物を出す先を教えてください"],
        "format": ["提出するファイルの形式は何ですか", "提出ファイルは何形式で、いくつ出しますか"],
        "office_hours": ["オフィスアワーの曜日と時間を教えてください", "質問を受け付けてもらえるのは何曜日の何時からですか"],
        "late": ["提出が締切に間に合わなかったらどうなりますか", "期限後に提出した課題は受理されますか"],
    },
    "test_extra_ungrounded": [
        "課題の文字数に制限はありますか", "提出した課題へのフィードバックはもらえますか",
        "参考文献の書き方に指定はありますか", "オフィスアワーは事前予約が必要ですか",
    ],
    "ungrounded_answer": "この FAQ には記載がありません。運営に確認が必要です。",
    # セクション 6 の知識質問。最後の 1 問は FAQ にある質問（対照）
    "knowledge_questions": [
        "この講座の最終課題の締切はいつですか",
        "担当教員の名前は何ですか",
        "次回の講義のテーマは何ですか",
        "課題の提出期限はいつですか",
    ],
}

# ---- 実装: 架空の暗号資産取引所の FAQ ----
# 講座 FAQ と同じ構造・同じ件数（train 14 / valid 7 / test 21）にする。変えたのは題材と SYSTEM の「講座 FAQ」の部分だけで、
# JSON の形式・UNGROUNDED_ANSWER・採点は講座 FAQ と同じ。

CRYPTO = {
    "system": "あなたは暗号資産取引所の FAQ の回答係です。与えられた FAQ だけを根拠に、必ず JSON 1 行で答えてください。形式: {\"answer\": 文字列, \"needs_review\": 真偽値}。FAQ に記載が無いことは answer に『確認が必要』と書き、needs_review を true にします。",
    "faq": {
        "fee": "現物取引の手数料は、メイカーが約定代金の 0.05%、テイカーが 0.10% です。",
        "withdrawal": "日本円の出金手数料は 1 回 330 円です。平日 15:00 までの出金申請は、その日のうちに振り込みます。",
        "kyc": "本人確認は、アプリで本人確認書類と顔写真を撮影して申請します。審査は通常 2 営業日以内に終わります。",
        "api": "API は 1 つの API キーにつき毎分 60 回まで呼び出せます。超えた場合は 1 分間エラーを返します。",
        "maintenance": "定期メンテナンスは毎週水曜 2:00〜4:00 で、その間は取引と入出金を停止します。",
    },
    "grounded": {
        "fee": (["取引手数料はいくらですか", "売買するときの手数料を教えてください", "メイカーとテイカーの手数料率は？", "現物の手数料は何%ですか"], ["0.05%", "0.10%"]),
        "withdrawal": (["日本円の出金手数料はいくらですか", "円を出金すると手数料はかかりますか", "出金した円はいつ振り込まれますか", "出金のルールを教えてください"], ["330 円", "15:00"]),
        "kyc": (["本人確認はどうやって行いますか", "口座開設の審査にはどれくらいかかりますか", "本人確認の手続きを教えてください", "審査が終わるまで何日かかりますか"], ["2 営業日"]),
        "api": (["API の呼び出し回数に制限はありますか", "API は1分間に何回まで使えますか", "API の上限を超えるとどうなりますか", "API のレート制限を教えてください"], ["60 回"]),
        "maintenance": (["メンテナンスはいつありますか", "取引できない時間帯はありますか", "定期メンテナンスの時間を教えてください", "毎週メンテナンスで止まるのは何曜日ですか"], ["水曜", "2:00"]),
    },
    # 根拠なし。講座 FAQ と同じく 4 問ごとに train 2 / valid 1 / test 1 に振られるので、
    # ニアミスと範囲外（UNGROUNDED_KIND）が train にも test にも入るように並べている
    "ungrounded": [
        "先物取引の手数料はいくらですか", "法人でも口座を開設できますか",
        "暗号資産を外部のウォレットに送るときの手数料はいくらですか", "API キーは何個まで発行できますか",
        "臨時メンテナンスはどこで告知されますか", "レバレッジは何倍までかけられますか",
        "未成年でも口座を作れますか", "日本円の入金に手数料はかかりますか",
    ],
    "test_extra_grounded": {
        "fee": ["現物取引の売買手数料の料率を教えてください", "メイカー手数料とテイカー手数料はそれぞれ何%ですか"],
        "withdrawal": ["円を引き出すときの手数料と、振り込みのタイミングを教えてください", "出金の手数料と、当日中に振り込まれる申請の締め時刻を教えてください"],
        "kyc": ["本人確認の審査は何日で終わりますか", "口座開設を申し込んでから審査完了までの目安は？"],
        "api": ["API キー1つあたりの呼び出し上限は毎分何回ですか", "API を使いすぎたときの上限と、超えたときの扱いを教えてください"],
        "maintenance": ["毎週のメンテナンスは何曜日の何時からですか", "メンテナンスで入出金が止まるのは何曜日の何時ですか"],
    },
    "test_extra_ungrounded": [
        "ステーキングの年利はどれくらいですか", "取り扱っている銘柄はいくつありますか",
        "本人確認書類にマイナンバーカードは使えますか", "メンテナンスの前に出した注文は取り消されますか",
    ],
    "ungrounded_answer": "この FAQ には記載がありません。運営に確認が必要です。",
    "knowledge_questions": [
        "この取引所を運営している会社はどこですか",
        "ビットコインの最小注文数量はいくつですか",
        "来月新しく上場する銘柄は何ですか",
        "取引手数料はいくらですか",
    ],
}

# 根拠なしの質問の種類。near: FAQ の項目と同じ話題で、書かれていない点を聞く（ニアミス）。out: FAQ の範囲外
CRYPTO_UNGROUNDED_KIND = {
    "先物取引の手数料はいくらですか": "near",
    "法人でも口座を開設できますか": "out",
    "暗号資産を外部のウォレットに送るときの手数料はいくらですか": "near",
    "API キーは何個まで発行できますか": "near",
    "臨時メンテナンスはどこで告知されますか": "near",
    "レバレッジは何倍までかけられますか": "out",
    "未成年でも口座を作れますか": "out",
    "日本円の入金に手数料はかかりますか": "near",
    "ステーキングの年利はどれくらいですか": "out",
    "取り扱っている銘柄はいくつありますか": "out",
    "本人確認書類にマイナンバーカードは使えますか": "near",
    "メンテナンスの前に出した注文は取り消されますか": "near",
}

FAQ_SETS = {"course": COURSE, "crypto": CRYPTO}


def make_example(question: str, answer: str, needs_review: bool, faq_text: str) -> dict:
    target = json.dumps({"answer": answer, "needs_review": needs_review}, ensure_ascii=False)
    return {"question": question, "faq": faq_text, "target": target, "needs_review": needs_review}


def split_templates(templates):
    # テンプレートの先頭 2 つを train、3 つ目を valid、4 つ目を test に固定（言い換えを跨がせない）
    return templates[:2], templates[2:3], templates[3:4]


def build_splits(data: dict) -> dict:
    """ノートブックのセクション 2 と同じ手順で train / valid / test / gold を作る。"""
    faq = data["faq"]
    faq_text = "\n".join(f"- {v}" for v in faq.values())
    train, valid, test, gold = [], [], [], {}
    for key, (templates, must_include) in data["grounded"].items():
        tr, va, te = split_templates(templates)
        for q in tr: train.append(make_example(q, faq[key], False, faq_text))
        for q in va: valid.append(make_example(q, faq[key], False, faq_text))
        for q in te + data["test_extra_grounded"][key]:
            test.append(make_example(q, faq[key], False, faq_text)); gold[q] = {"needs_review": False, "must_include": must_include}
    for i, q in enumerate(data["ungrounded"]):
        ex = make_example(q, data["ungrounded_answer"], True, faq_text)
        bucket = [train, train, valid, test][i % 4]   # 根拠なしの質問は 4 問ごとに train 2 / valid 1 / test 1 に振る
        bucket.append(ex)
        if bucket is test: gold[q] = {"needs_review": True, "must_include": ["確認"]}
    for q in data["test_extra_ungrounded"]:
        test.append(make_example(q, data["ungrounded_answer"], True, faq_text)); gold[q] = {"needs_review": True, "must_include": ["確認"]}

    all_questions = [r["question"] for r in train + valid + test]
    assert len(set(all_questions)) == len(all_questions), "質問が train / valid / test のどこかで重複しています。テンプレートを見直してください"
    return {"faq_text": faq_text, "train": train, "valid": valid, "test": test, "gold": gold}


# ---- 発展: 用語集についての評価セット ----
# A: 用語集にある語を、学習データ（scripts/make_sft_dataset.py）に無い言い回しで聞く
# B: 言い回しを変えた質問（別名・応用・説明から用語を答えさせる逆向き・講座に固有のことの言い換え）
# C: 用語集にない語（実在する語と架空の語）。望ましい答えは「用語集には載っていません」
# must_include の要素は、文字列か「どれか 1 つを含めばよい」候補のリスト。比べるときは normalize してから比べる

GLOSSARY_CATEGORIES = {"A": "用語集にある語", "B": "言い回しを変えた質問", "C": "用語集にない語"}
EVAL_TEMPLATE = "「{term}」の意味を教えてください。"
ONE_OF = ["どれか1つ", "どれか一つ", "いずれか1つ", "いずれか一つ"]


def _a(term_id: str, term: str, must_include: list) -> dict:
    return {"category": "A", "question": EVAL_TEMPLATE.format(term=term), "term_id": term_id, "must_include": must_include}


def _b(term_id: str, question: str, must_include: list, kind: str) -> dict:
    return {"category": "B", "question": question, "term_id": term_id, "must_include": must_include, "kind": kind}


def _c(term: str, kind: str) -> dict:
    return {"category": "C", "question": EVAL_TEMPLATE.format(term=term), "term_id": None, "must_include": [], "kind": kind, "term": term}


GLOSSARY_EVAL = [
    _a("lora", "LoRA", ["低ランク", "固定"]),
    _a("overfitting", "過学習", ["検証データ"]),
    _a("temperature", "temperature", ["ランダム"]),
    _a("hallucination", "ハルシネーション", [["事実と異なる", "存在しない"]]),
    _a("epoch", "エポック", [["1周", "一周", "1巡", "一巡"]]),
    _a("homework-levels", "宿題の3レベル", ["基礎", "実装", "発展", ONE_OF]),
    _a("lec-start-tag", "lecNN-start タグ", ["開始時点", "ブランチ"]),
    _a("default-model", "既定モデル", ["gemini-3.5-flash-lite"]),
    _a("codespaces-secret", "Codespaces secret", ["環境変数"]),
    _a("test-model", "TestModel", ["Pydantic AI", "テスト"]),
    _b("lora", "Low-Rank Adaptation という手法を説明してください。", ["低ランク", "固定"], "別名"),
    _b("default-model", "AIE2026 のデフォルトモデルは何ですか？", ["gemini-3.5-flash-lite"], "別名"),
    _b("qlora", "LoRA と QLoRA の違いは何ですか？", [["量子化", "4ビット", "4bit"]], "応用"),
    _b("lora-rank", "LoRA の r を大きくすると、どうなりますか？", ["表現力", ["パラメータ", "メモリ"]], "応用"),
    _b("api-key", "Gemini の API キーは、コードに直接書いてもいいですか？", [["書かない", "書いてはいけ", "書くべきではない", "書くべきではありません", "避け"]], "応用"),
    _b("homework-levels", "AIE2026 の宿題は、毎回すべてのレベルに取り組む必要がありますか？", [ONE_OF], "講座の言い換え"),
    _b("overfitting", "学習データにだけ過度に適合して、未知の入力で性能が落ちる状態を何と呼びますか？", ["過学習"], "逆向き"),
    _b("learning-rate", "1回の更新でパラメータをどれだけ動かすかを決めるハイパーパラメータは何ですか？", ["学習率"], "逆向き"),
    _b("lec-start-tag", "前の回の演習が終わっていなくても、その回の演習を始めるために使う Git のタグを何と言いますか？", [["lecNN-start", "lec03-start"]], "逆向き"),
    _b("quantization", "モデルの重みを4ビットなど少ないビット数で表して、メモリを減らす技術は何ですか？", ["量子化"], "逆向き"),
    _c("DPO", "実在"),
    _c("蒸留", "実在"),
    _c("Transformer", "実在"),
    _c("RLHF", "実在"),
    _c("MoE", "実在"),
    _c("埋め込みベクトル", "実在"),
    _c("プロンプトインジェクション", "実在"),
    _c("lecNN-end タグ", "架空"),
    _c("宿題の5レベル", "架空"),
    _c("TurboModel", "架空"),
]

# C で「答えを控えた」とみなす言い回し
ABSTAIN_MARKERS = [
    "載っていません", "用語集にはありません", "用語集にありません", "見つかりません",
    "わかりません", "分かりません", "存在しません", "知りません", "情報がありません", "確認できません",
]

# 検索＋素のモデル（RAG）で使う指示
RAG_SYSTEM = "あなたは講座の用語集にもとづいて質問に答える係です。与えられた検索結果だけを根拠に、日本語で簡潔に答えてください。検索結果に答えが無いときは「用語集には載っていません。」と答えてください。"


def normalize(text: str) -> str:
    """全角・半角、大文字・小文字、空白の違いを無視して比べるための正規化。"""
    return unicodedata.normalize("NFKC", text).casefold().replace(" ", "")


def contains_all(answer: str, must_include: list) -> bool:
    text = normalize(answer)
    return all(any(normalize(w) in text for w in ([k] if isinstance(k, str) else k)) for k in must_include)


def abstained(answer: str) -> bool:
    text = normalize(answer)
    return any(normalize(m) in text for m in ABSTAIN_MARKERS)


def score_glossary_answer(answer: str, item: dict) -> bool:
    """A・B は必須語句をすべて含めば正解。C は答えを控えれば正解。"""
    if item["category"] == "C":
        return abstained(answer)
    return contains_all(answer, item["must_include"])


def search_query(question: str) -> str:
    """検索に渡す語。「」で用語を示した質問はその用語を、そうでない質問は質問文をそのまま渡す。"""
    m = re.search(r"「(.+?)」", question)
    return m.group(1) if m else question
