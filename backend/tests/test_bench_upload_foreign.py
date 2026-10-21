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


def _err(fn) -> dict:
    with pytest.raises(HTTPException) as e:
        fn()
    assert e.value.status_code == 422
    return e.value.detail


def _code(fn) -> str:
    return _err(fn)["code"]


def test_foreign_json_shape_gives_clear_422():
    j = {"jobs": [{"job_id": "J-1", "description": "Middle Python: Django, PostgreSQL"}],
         "resumes": [{"resume_id": "R-1", "skills": "Python, Django"}],
         "judgments": [{"job": "J-1", "resume": "R-1", "score": 3}]}
    assert _code(lambda: ev(json.dumps(j), "json", 5)) == "no_needs"


def test_foreign_qrels_csv_gives_clear_422():
    body = _csv([("q1", "Middle Python backend", "d1", "Python FastAPI", 3)],
                head=["query_id", "query_text", "doc_id", "doc_text", "label"])
    assert _code(lambda: ev(body, "csv", 5)) == "invalid_csv_row"


def test_format_errors_point_to_sample_and_fields():
    """Ошибка формата объясняет, что ждём, и даёт адрес образца (п. 4 замечаний «свой набор пар»)."""
    d = _err(lambda: ev(json.dumps({"jobs": [], "resumes": []}), "json", 5))
    assert d["code"] == "no_needs"
    for word in ("/api/employer/benchmark/sample", "needs", "candidates", "labels", "relevance"):
        assert word in d["message"]
    d = _err(lambda: ev(json.dumps([1, 2]), "json", 5))
    assert d["code"] == "invalid_json_root" and "/api/employer/benchmark/sample" in d["message"]
    d = _err(lambda: ev(_csv([("q1", "x", "d1", "y", 1)], head=["query_id", "query_text", "doc_id", "doc_text", "label"]), "csv", 5))
    assert "/api/employer/benchmark/sample?format=csv" in d["message"]


def test_label_scale_is_one_for_whole_file():
    """Шкала по всему файлу (п. 1): вакансия, где эксперт поставил только 0/1 при общей шкале 0–3, считается по порогу 2.

    Раньше порог выбирался по каждой вакансии: у V2 (оценки 1 и 0) кандидат с «1» считался релевантным, хотя по шкале
    файла 0–3 «1» — «слабо подходит». Ожидание: у V2 нет релевантных, P@5 и MRR = 0; у V1 (оценка 3) — MRR > 0.
    """
    rows = [list(p) for p in PAIRS]
    rows[0][-1] = 3  # V1/C1 — оценка 3: файл на шкале 0–3
    r = ev(_csv([tuple(x) for x in rows]), "csv", 5)
    assert r["label_scale"] == {"max": 3, "threshold": 2,
                                "text": "Шкала 0–3 по всему файлу: релевантен кандидат с оценкой не ниже 2."}
    by = {n["need_id"]: n["metrics"] for n in r["per_need"]}
    assert by["V1"]["mrr"] > 0
    assert by["V2"]["p@5"] == 0 and by["V2"]["mrr"] == 0
    # файл только 0/1 — порог 1 для всех вакансий
    b = ev(_csv(PAIRS), "csv", 5)
    assert b["label_scale"]["max"] == 1 and b["label_scale"]["threshold"] == 1
    assert {n["need_id"]: n["metrics"]["mrr"] for n in b["per_need"]}["V2"] > 0


def test_note_has_no_internal_codes():
    """Пояснение под результатом — понятным языком (п. 2): без уровней T0/T1/T2 и других внутренних кодов."""
    import re

    from app.modules.matching.bench_upload import sample_dataset_response

    body, _, _ = sample_dataset_response("json")
    for r in (ev(body, "json", 5), ev(_csv(PAIRS), "csv", 5)):
        assert not re.search(r"\bT[0-3]\b|θ|IRT", r["note"]), r["note"]
        assert "тест" in r["note"] and "резюме" in r["note"]


def test_fairness_counts_people_not_pairs():
    """Правило 4/5 считает людей (п. 3): каждый кандидат входит в расчёт один раз, сколько бы вакансий ни было в файле.

    Раньше знаменатель — пары вакансия × кандидат (в образце 2 вакансии × 5 кандидатов = 10 «человек» из 5).
    """
    from app.modules.matching.bench_upload import sample_dataset_response

    body, _, _ = sample_dataset_response("json")
    r = ev(body, "json", 5)
    f = r["fairness"]
    assert f["unit"] == "people"
    assert 0 < f["n_without_fsp"] + f["n_with_fsp"] <= r["n_candidates"]
    assert f["n_with_fsp"] > 0 and f["n_without_fsp"] > 0
    # доли — отобранные люди / люди в группе; «отобран» = в первых 5 хотя бы одной вакансии
    top = {x["candidate_id"] for n in r["per_need"] for x in n["results"][:5]}
    assert f["selection_rate_with_fsp"] <= 1 and f["selection_rate_without_fsp"] <= 1
    assert all("_eligible_ids" not in n for n in r["per_need"])  # служебное поле не уходит в ответ
    assert top  # выдача не пуста
    # CSV пар: 6 людей, 2 вакансии — в расчёте не больше 6, а не 12
    p = ev(_csv(PAIRS), "csv", 5)["fairness"]
    assert p["n_without_fsp"] + p["n_with_fsp"] <= 6
