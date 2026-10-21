"""Их ранжировщик и их базовая линия на подмножестве вакансий — запускается ИХ окружением (отдельный процесс:
у обоих репозиториев корневой пакет называется app). Вход: --src клон, --ids файл со списком id вакансий; выход — JSON."""
import argparse, json, os, sys

ap = argparse.ArgumentParser()
ap.add_argument("--src", required=True)
ap.add_argument("--ids", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()
sys.path.insert(0, os.path.join(a.src, "backend"))
from app.validation.external_eval import evaluate_external  # noqa: E402

data = json.load(open(os.path.join(a.src, "docs/examples/eval_pairs_example.json"), encoding="utf-8"))
ids = set(json.load(open(a.ids)))
sub = {"vacancies": [v for v in data["vacancies"] if str(v["id"]) in ids], "candidates": data["candidates"],
       "labels": [lb for lb in data["labels"] if str(lb["vacancy"]) in ids]}
json.dump(evaluate_external(sub), open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
