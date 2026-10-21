"""«Проверить на своём наборе пар» (MatchingBenchUpload): файлы чужой формы, как их принесёт эксперт.

Найдено прогоном на пробном стенде 2а 21.10: плоский CSV пар с навыками строкой («Python, Flask, MySQL») давал 500 —
find_stack возвращает словарь {тег: позиция}, а код брал found[0] (KeyError). Здесь: такой файл считается (метрики
есть), чужая форма JSON/CSV — понятная ошибка 422 с кодом, оценки 0/1 — порог релевантности 1.
"""
from __future__ import annotations

import csv
import io
import json

import pytest
from fastapi import HTTPException

from app.modules.matching.bench_upload import evaluate_uploaded_dataset as ev

HEAD = ["need_id", "need_text", "need_direction", "need_grade", "candidate_id", "candidate_direction",
        "candidate_grade", "skills", "relevance"]
V1 = ("V1", "Backend middle: Python, FastAPI, PostgreSQL, Docker обязательно", "backend", "middle")
V2 = ("V2", "Frontend middle: TypeScript, React, HTML/CSS", "frontend", "middle")
PAIRS = [V1 + ("C1", "backend", "middle", "Python, FastAPI, PostgreSQL, Docker", 1),
         V1 + ("C2", "backend", "middle", "Python, Flask, MySQL", 0),
         V1 + ("C3", "backend", "middle", "Go, PostgreSQL, Docker, Kubernetes", 0),
         V1 + ("C4", "backend", "middle", "Python, FastAPI, PostgreSQL", 1),
         V2 + ("C5", "frontend", "middle", "TypeScript, React, CSS", 1),
         V2 + ("C6", "frontend", "middle", "Angular, RxJS", 0)]


def _csv(rows, head=HEAD) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(head)
    w.writerows(rows)
    return buf.getvalue()


def test_flat_pairs_with_skill_strings_are_evaluated():
    r = ev(_csv(PAIRS), "csv", 5)
    assert r["n_needs"] == 2 and r["n_candidates"] == 6 and r["n_labels"] == 6
    assert r["evaluated_needs"] == 2
    for m in ("p@5", "ndcg@10", "mrr"):
        assert 0.0 <= r["summary"][m] <= 1.0
    # бинарные оценки: релевантен тот, у кого 1 (порог 2 дал бы P@5 = 0 при идеальном порядке)
    assert r["summary"]["mrr"] > 0


def _code(fn) -> str:
    with pytest.raises(HTTPException) as e:
        fn()
    assert e.value.status_code == 422
    return e.value.detail["code"]


def test_foreign_json_shape_gives_clear_422():
    j = {"jobs": [{"job_id": "J-1", "description": "Middle Python: Django, PostgreSQL"}],
         "resumes": [{"resume_id": "R-1", "skills": "Python, Django"}],
         "judgments": [{"job": "J-1", "resume": "R-1", "score": 3}]}
    assert _code(lambda: ev(json.dumps(j), "json", 5)) == "no_needs"


def test_foreign_qrels_csv_gives_clear_422():
    body = _csv([("q1", "Middle Python backend", "d1", "Python FastAPI", 3)],
                head=["query_id", "query_text", "doc_id", "doc_text", "label"])
    assert _code(lambda: ev(body, "csv", 5)) == "invalid_csv_row"
