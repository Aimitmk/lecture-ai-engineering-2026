"""第2回 宿題のデータと集計のテスト（torch もモデルも使わない）。"""

import ast
import contextlib
import io
import json
from pathlib import Path

from app import tools
from scripts import lora_data, lora_homework, make_sft_dataset

ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK = ROOT / "notebooks" / "lora_format_tuning.ipynb"


def notebook_cell(cell_id: str) -> str:
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    return "".join(next(c for c in cells if c.get("id") == cell_id)["source"])


def notebook_literals(cell_id: str) -> dict:
    """セルの中の「名前 = リテラル」の代入を読み出す（セルは実行しない）。"""
    values = {}
    for node in ast.parse(notebook_cell(cell_id)).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return values


def test_course_data_is_copied_from_notebook():
    data = notebook_literals("9ea1a92c")
    assert lora_data.COURSE["faq"] == data["FAQ"]
    assert lora_data.COURSE["grounded"] == data["GROUNDED"]
    assert lora_data.COURSE["ungrounded"] == data["UNGROUNDED"]
    assert lora_data.COURSE["test_extra_grounded"] == data["TEST_EXTRA_GROUNDED"]
    assert lora_data.COURSE["test_extra_ungrounded"] == data["TEST_EXTRA_UNGROUNDED"]
    assert lora_data.COURSE["ungrounded_answer"] == data["UNGROUNDED_ANSWER"]
    assert lora_data.COURSE["system"] == notebook_literals("d7dc2471")["SYSTEM"]
    assert lora_data.COURSE["knowledge_questions"] == notebook_literals("51e56a48")["KNOWLEDGE_QUESTIONS"]


def test_config_is_copied_from_notebook():
    config = notebook_literals("09c69560")["CONFIG"]
    assert lora_homework.BASE_CONFIG == {k: v for k, v in config.items() if k not in ("work_dir", "drive_dir")}


def test_build_splits_matches_notebook(tmp_path):
    # ノートブックのデータ生成セルをそのまま実行し、移した build_splits と同じ分割になることを確かめる
    ns = {"json": json, "WORK": tmp_path}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(notebook_cell("9ea1a92c"), ns)
    splits = lora_data.build_splits(lora_data.COURSE)
    for key in ("train", "valid", "test", "gold"):
        assert splits[key] == ns[key], key
    assert (len(splits["train"]), len(splits["valid"]), len(splits["test"])) == (14, 7, 21)


def test_crypto_has_same_shape_as_course():
    splits = lora_data.build_splits(lora_data.CRYPTO)
    assert (len(splits["train"]), len(splits["valid"]), len(splits["test"]), len(splits["gold"])) == (14, 7, 21, 21)
    assert sum(r["needs_review"] for r in splits["train"]) == 4
    assert sum(g["needs_review"] for g in splits["gold"].values()) == 6
    # 根拠なしの質問には種類（ニアミス・範囲外）が付いていて、train にも test にも両方の種類が入っている
    ungrounded = lora_data.CRYPTO["ungrounded"] + lora_data.CRYPTO["test_extra_ungrounded"]
    assert set(lora_data.CRYPTO_UNGROUNDED_KIND) == set(ungrounded)
    for split in ("train", "test"):
        kinds = {lora_data.CRYPTO_UNGROUNDED_KIND[r["question"]] for r in splits[split] if r["needs_review"]}
        assert kinds == {"near", "out"}, split
    # 対照の知識質問は FAQ にある質問、ほかの 3 問は FAQ に無い質問
    assert lora_data.CRYPTO["knowledge_questions"][-1] == lora_data.CRYPTO["grounded"]["fee"][0][0]
    # SYSTEM は「講座 FAQ」の部分だけを替えている
    assert lora_data.CRYPTO["system"] == lora_data.COURSE["system"].replace("講座 FAQ", "暗号資産取引所の FAQ")


def test_glossary_sft_is_unmodified_script_output():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        make_sft_dataset.main()
    assert (ROOT / "lectures" / "02" / "data" / "glossary_sft.jsonl").read_text(encoding="utf-8") == out.getvalue()


def test_glossary_eval_set():
    glossary = {t["id"]: t for t in tools.load_glossary()}
    items = lora_data.GLOSSARY_EVAL
    assert [sum(i["category"] == c for i in items) for c in "ABC"] == [10, 10, 10]
    trained_questions = {json.loads(line)["messages"][0]["content"]
                         for line in (ROOT / "lectures" / "02" / "data" / "glossary_sft.jsonl").read_text(encoding="utf-8").splitlines()}
    for item in items:
        assert item["question"] not in trained_questions, item["question"]
        if item["category"] == "C":
            # 用語集にない語: 用語名・別名・定義のどこにも出てこない
            term = lora_data.normalize(item["term"])
            for t in glossary.values():
                texts = [t["term"], t["definition"], *t["aliases"]]
                assert all(term not in lora_data.normalize(x) for x in texts), (item["term"], t["id"])
        else:
            # 正解の用語は用語集にあり、必須語句はその定義（逆向きの質問なら用語名か別名）に含まれる
            t = glossary[item["term_id"]]
            expected = " ".join([t["term"], *t["aliases"]]) if item.get("kind") == "逆向き" else t["definition"]
            assert lora_data.contains_all(expected, item["must_include"]), item["question"]


def test_scoring_and_search_query():
    lora_item = lora_data.GLOSSARY_EVAL[0]
    assert lora_data.score_glossary_answer(next(t for t in tools.load_glossary() if t["id"] == "lora")["definition"], lora_item)
    assert not lora_data.score_glossary_answer("用語集には載っていません。", lora_item)
    c_item = next(i for i in lora_data.GLOSSARY_EVAL if i["category"] == "C")
    assert lora_data.score_glossary_answer("用語集には載っていません。", c_item)
    assert not lora_data.score_glossary_answer("DPO は、人の好みのデータで直接学習する手法です。", c_item)
    # 全角数字・空白・大文字小文字の違いは無視し、候補のどれか 1 つを含めばよい
    assert lora_data.contains_all("課題はどれか１つ で完了", [lora_data.ONE_OF])
    assert lora_data.search_query("「LoRA」の意味を教えてください。") == "LoRA"
    assert lora_data.search_query("LoRA と QLoRA の違いは何ですか？") == "LoRA と QLoRA の違いは何ですか？"


def test_failure_type():
    grounded = {"gold_needs_review": False, "content_ok": False}
    ungrounded = {"gold_needs_review": True, "content_ok": False}
    asserted = '{"answer": "課題の提出期限は 9 月 30 日 23:59（日本時間）です。", "needs_review": false}'
    assert lora_homework.failure_type({**ungrounded, "raw": asserted}, "near") == "根拠なしに断定（ニアミス）"
    escaped = '{"answer": "この FAQ には記載がありません。運営に確認が必要です。", "needs_review": true}'
    assert lora_homework.failure_type({**grounded, "raw": escaped}) == "根拠ありで逃げた"
    assert lora_homework.failure_type({**grounded, "raw": '{"answer": "PDF です。"}'}) == "形式の崩れ（missing_key）"
    assert lora_homework.failure_type({**grounded, "raw": "はい。" + escaped}) == "形式の崩れ（json_error: JSONDecodeError）＋根拠ありで逃げた"
    assert lora_homework.failure_type({**grounded, "raw": '{"answer": "提出先は学習ポータルです。", "needs_review": false}'}) == "語句が違う"
