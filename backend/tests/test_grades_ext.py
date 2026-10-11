"""Уровни Lead и Principal за флагом GRADES_EXT_ENABLED (по умолчанию выкл.).

Без флага — всё как раньше: 4 уровня, прежние API и справочник, разбор «Team Lead» → Senior. С флагом — 6 уровней,
Lead/Principal видны только в направлениях, где банк их проверяет; эти проверки — в tests/test_grades_ext_on.py,
который запускается отдельным процессом с GRADES_EXT_ENABLED=1 (флаг читается при импорте seed_data).
"""
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.catalog import levels
from app.modules.catalog.levels_seed import LEAD_MARKET, ensure, market_rows
from app.modules.catalog.models import Category, Grade
from app.modules.catalog.seed_data import (ALL_GRADE_CUTS, ALL_GRADE_LEVEL, ALL_GRADE_START_THETA, ALL_GRADES,
                                           EXT_GRADE_ORDER, GRADE_CUTS, GRADE_ORDER, GRADE_START_THETA, GRADES,
                                           GRADES_EXT, grade_by_experience)
from app.modules.matching.need_parser import parse_rules

BACKEND = Path(__file__).resolve().parents[1]


def test_without_flag_four_levels_as_before():
    assert not GRADES_EXT and not levels.enabled()
    assert GRADE_ORDER == ("intern", "junior", "middle", "senior")
    assert set(GRADES) == set(GRADE_CUTS) == set(GRADE_START_THETA) == set(GRADE_ORDER)
    assert GRADE_CUTS == {"intern": -1.75, "junior": -1.0, "middle": 0.0, "senior": 1.0}
    assert levels.available_grades("backend") == GRADE_ORDER and levels.top_grade("qa") == "senior"
    assert levels.cap("backend", "lead") == "senior" and levels.cap("backend", "middle") == "middle"
    assert grade_by_experience(12) == "senior"


def test_ext_constants_agreed_cuts():
    # согласовано с расчётом точности уровня: полосы Senior и Lead шириной 1, как Junior/Middle
    assert EXT_GRADE_ORDER == ("lead", "principal")
    assert ALL_GRADE_CUTS["lead"] == 2.0 and ALL_GRADE_CUTS["principal"] == 3.0
    assert ALL_GRADE_START_THETA["lead"] == 2.4 and ALL_GRADE_START_THETA["principal"] == 3.3
    assert ALL_GRADE_LEVEL["lead"] == 4 and ALL_GRADE_LEVEL["principal"] == 5
    assert ALL_GRADES["lead"] == "Lead" and ALL_GRADES["principal"] == "Principal"
    cuts = [ALL_GRADE_CUTS[g] for g in sorted(ALL_GRADE_LEVEL, key=ALL_GRADE_LEVEL.get)]
    assert cuts == sorted(cuts)


def test_need_parser_team_lead_stays_senior_without_flag():
    r = parse_rules("Team Lead Python backend: FastAPI, PostgreSQL, Kafka; руководство командой из 6 человек")
    assert r["grade"] == "senior" and "grade_capped_from" not in r


def test_openapi_claimed_grade_enum_unchanged(client):
    spec = client.get("/api/openapi.json").json()
    found = []
    for sch in spec["components"]["schemas"].values():
        p = (sch.get("properties") or {}).get("claimed_grade")
        if p and "enum" in p:
            found.append(p["enum"])
    assert found and all(e == list(GRADE_ORDER) for e in found)


def test_meta_has_no_grades_ext_without_flag(client):
    assert "grades_ext" not in client.get("/api/meta").json()


def test_market_rows_lead_from_habr_principal_estimate():
    rows = {r["grade_id"]: r for r in market_rows("backend", "Backend")}
    lead, pr = rows["lead"], rows["principal"]
    assert (lead["market_salary_from"], lead["market_salary_to"], lead["market_salary_median"]) == (345000, 550000, 450000)
    assert lead["market_sample_size"] == 890 and "Хабр" in lead["market_source"]
    assert pr["market_salary_from"] == lead["market_salary_to"] and pr["market_salary_median"] is None
    assert "оценка" in pr["market_source"]
    assert market_rows("mobile", "Mobile") == []  # нет данных — нет категорий
    assert all(v[0] < v[1] and v[0] % 5000 == 0 and v[1] % 5000 == 0 for v in LEAD_MARKET.values())


def test_ensure_noop_without_flag_and_catalog_hides_leftover_rows(client):
    with SessionLocal() as db:
        assert ensure(db) == {"enabled": False, "grades": 0, "categories": 0}
        assert db.get(Grade, "lead") is None
        try:
            res = ensure(db, force=True)  # строки остались в БД (флаг включали и выключили)
            assert res["grades"] == 2 and res["categories"] >= 10
            assert ensure(db, force=True)["categories"] == 0  # идемпотентно
            cat = client.get("/api/catalog").json()
            assert {g["id"] for g in cat["grades"]} == set(GRADE_ORDER)
            assert not any(c["id"].endswith((".lead", ".principal")) for c in cat["categories"])
        finally:  # справочные таблицы между тестами не чистятся — убрать за собой
            for c in db.scalars(select(Category).where(Category.grade_id.in_(EXT_GRADE_ORDER))).all():
                db.delete(c)
            db.flush()
            for g in db.scalars(select(Grade).where(Grade.id.in_(EXT_GRADE_ORDER))).all():
                db.delete(g)
            db.commit()


def test_with_flag_suite_in_subprocess():
    """tests/test_grades_ext_on.py — отдельным процессом с GRADES_EXT_ENABLED=1 (своя временная БД)."""
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "PYTEST_XDIST_WORKER",
                                                           "PYTEST_XDIST_WORKER_COUNT", "PYTEST_CURRENT_TEST")}
    env["GRADES_EXT_ENABLED"] = "1"
    env.pop("TEST_DATABASE_URL", None)  # общий PostgreSQL занят основным прогоном — флаг проверяем на своём SQLite
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "-p", "no:randomly",
                        "tests/test_grades_ext_on.py"], cwd=BACKEND, env=env, capture_output=True, text=True,
                       timeout=900)
    assert r.returncode == 0, (r.stdout[-4000:] + r.stderr[-2000:])
    assert " passed" in r.stdout and "skipped" not in r.stdout.split("\n")[-2]


def test_validation_grades_ext_route_absent_without_flag(client):
    assert client.get("/api/validation/grades-ext").status_code == 404
    assert "/api/validation/grades-ext" not in client.get("/api/openapi.json").json()["paths"]
