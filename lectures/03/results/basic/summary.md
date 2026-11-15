# 第3回 宿題（基礎）: 実行ごとのツール呼び出し

`uv run --frozen python -m scripts.lec03_prompt_variants --summary` の出力。gemini-3.5-flash-lite、commit bbc8d50、2026-11-15 11:58〜12:05 JST、ローカルの macOS。

| 質問 | 条件 | 回 | ツール呼び出し（順） | requests | 入力 / 出力 tokens | 最後の行に第N回 |
|---|---|---:|---|---:|---:|:---:|
| 3levels | baseline | 1 | `search_glossary(query='3レベル')` | 2 | 985 / 174 | ○ |
| 3levels | baseline | 2 | `search_glossary(query='3レベル')` | 2 | 985 / 117 | ○ |
| 3levels | baseline | 3 | `search_glossary(query='3レベル')` | 2 | 985 / 128 | ○ |
| 3levels | no_must_search | 1 | `search_glossary(query='3レベル')` | 2 | 937 / 137 | ○ |
| 3levels | no_must_search | 2 | `search_glossary(query='3レベル')` | 2 | 937 / 134 | ○ |
| 3levels | no_must_search | 3 | `search_glossary(query='3レベル')` | 2 | 937 / 145 | ○ |
| 3levels | docstring_batch | 1 | `search_glossary(query='3レベル')` | 2 | 981 / 189 | ○ |
| 3levels | docstring_batch | 2 | `search_glossary(query='3レベル')` | 2 | 981 / 138 | ○ |
| 3levels | docstring_batch | 3 | `search_glossary(query='3レベル')` | 2 | 981 / 124 | ○ |
| 3levels | end_with_quiz | 1 | `search_glossary(query='3レベル')` | 2 | 971 / 162 | － |
| 3levels | end_with_quiz | 2 | `search_glossary(query='3レベル')` | 2 | 971 / 192 | － |
| 3levels | end_with_quiz | 3 | `search_glossary(query='3レベル')` | 2 | 971 / 191 | － |
| lora_qlora | baseline | 1 | `search_glossary(query='LoRA')`<br>`search_glossary(query='QLoRA')` | 2 | 1,398 / 223 | ○ |
| lora_qlora | baseline | 2 | `search_glossary(query='LoRA')`<br>`search_glossary(query='QLoRA')` | 2 | 1,398 / 224 | ○ |
| lora_qlora | baseline | 3 | `search_glossary(query='LoRA')`<br>`search_glossary(query='QLoRA')` | 2 | 1,398 / 181 | ○ |
| lora_qlora | no_must_search | 1 | `search_glossary(query='LoRA')`<br>`search_glossary(query='QLoRA')` | 2 | 1,350 / 213 | ○ |
| lora_qlora | no_must_search | 2 | `search_glossary(query='LoRA')`<br>`search_glossary(query='QLoRA')` | 2 | 1,350 / 194 | ○ |
| lora_qlora | no_must_search | 3 | `search_glossary(query='LoRA')`<br>`search_glossary(query='QLoRA')` | 2 | 1,350 / 186 | ○ |
| lora_qlora | docstring_batch | 1 | `search_glossary(query='LoRA QLoRA')` | 2 | 1,087 / 195 | ○ |
| lora_qlora | docstring_batch | 2 | `search_glossary(query='LoRA QLoRA')` | 2 | 1,087 / 185 | ○ |
| lora_qlora | docstring_batch | 3 | `search_glossary(query='LoRA QLoRA')` | 2 | 1,087 / 204 | ○ |
| lora_qlora | end_with_quiz | 1 | `search_glossary(query='LoRA')`<br>`search_glossary(query='QLoRA')` | 2 | 1,384 / 297 | － |
| lora_qlora | end_with_quiz | 2 | `search_glossary(query='LoRA')`<br>`search_glossary(query='QLoRA')` | 2 | 1,384 / 244 | － |
| lora_qlora | end_with_quiz | 3 | `search_glossary(query='LoRA')`<br>`search_glossary(query='QLoRA')` | 2 | 1,384 / 242 | － |
| quiz | baseline | 1 | `make_quiz(lecture=2)` | 2 | 921 / 47 | ○ |
| quiz | baseline | 2 | `make_quiz(lecture=2)` | 2 | 918 / 61 | ○ |
| quiz | baseline | 3 | `make_quiz(lecture=2)` | 2 | 924 / 56 | ○ |
