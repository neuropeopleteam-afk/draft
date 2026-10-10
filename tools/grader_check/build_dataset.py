"""Сборка проверочного набора оценщика открытых ответов из панели 06.10 (один раз, результат лежит в репозитории).

Источник — оценщик по рубрике второй панели (`bank/calibration/rubric_grade.py`, внутренний отчёт разработки):
* набор A — 232 ответа на 29 развёрнутых заданий: эталоны рубрики strong / medium / weak, атака-инъекция,
  «общие слова», 87 ответов gpt-oss-120b;
* набор B — ответы открытых моделей панели (слот 0), которые на панели оценили и YandexGPT, и gpt-oss-120b
  (Llama 3.1 8B, Qwen2.5-Coder 7B и 32B — 87 ответов).

Задания (условие, код, вопрос шага, рубрика) восстанавливаются генератором банка того же коммита, на котором
отвечали модели панели (1631167), — иначе рубрика могла бы не совпасть с заданием:

    git -C <bank> archive 1631167 | tar -x -C /tmp/oldbank
    <venv_bank>/bin/python tools/grader_check/build_dataset.py --oldbank /tmp/oldbank \
        --grading <panel2_raw>/grading --out docs/validation/grader_set_panel_20261006.json.gz

Оценки панели (старый промпт приложения, один вызов на ответ, без фильтра инъекций) кладутся рядом —
это столбец «до» в отчёте /validation.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oldbank", required=True)
    ap.add_argument("--grading", required=True, help="каталог panel2_raw/grading")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    sys.path.insert(0, str(Path(a.oldbank) / "calibration"))
    sys.path.insert(0, a.oldbank)
    from rubric_grade import variant  # noqa: E402

    g = Path(a.grading)
    answers: dict[str, dict] = {}
    for fn, set_name in (("grade_A.jsonl", "A"), ("grade_B_ygpt.jsonl", "B")):
        for line in open(g / fn, encoding="utf-8"):
            o = json.loads(line)
            answers[o["req_id"]] = {"id": o["req_id"], "set": set_name, "source": o["source"], "model": o["model"],
                                    "item": f"{o['family_id']}|{o['seed']}", "item_id": o["item_id"],
                                    "answer": o["answer"]}
    for fn, key in (("grades_ygpt.csv", "yandexgpt"), ("grades_gptoss.csv", "gptoss")):
        for r in csv.DictReader(open(g / fn, encoding="utf-8")):
            if r["req_id"] in answers and r["status"] in ("scored", "rule"):
                answers[r["req_id"]].setdefault("panel", {})[key] = float(r["score"])
    items = {}
    for x in answers.values():
        if x["item"] not in items:
            fid, seed = x["item"].split("|")
            v = variant(fid, int(seed))
            items[x["item"]] = {"family_id": fid, "seed": int(seed), "format": v["format"], "stem": v["stem"],
                                "code": v["code"], "step_prompt": v["step_prompt"], "rubric": v["rubric"]}
    out = {"source": "panel 06.10 (bank 1631167), внутренний отчёт разработки",
           "note": "A: эталоны, инъекция, общие слова, ответы gpt-oss-120b; B: ответы открытых моделей (слот 0)",
           "items": items, "answers": sorted(answers.values(), key=lambda x: x["id"])}
    with gzip.open(a.out, "wt", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    n_a = sum(1 for x in answers.values() if x["set"] == "A")
    print(f"заданий {len(items)}, ответов {len(answers)} (A {n_a}, B {len(answers) - n_a}) → {a.out}")


if __name__ == "__main__":
    main()
