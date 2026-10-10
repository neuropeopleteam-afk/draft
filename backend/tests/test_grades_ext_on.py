"""Lead и Principal при включённом флаге: запускается из tests/test_grades_ext.py отдельным процессом с
GRADES_EXT_ENABLED=1 (флаг читается при импорте seed_data). В обычном прогоне без флага модуль пропускается.

Банк заменён подменой ``levels.bank_ext_families``: backend — 2 Lead + 1 Principal своих, qa — 1 Lead своё,
frontend — ничего; общий блок — 2 Lead + 2 Principal (порог видимости: своих ≥ 1, вместе с общим ≥ 3).
"""
import pytest
from sqlalchemy import select

from app.modules.catalog import seed_data

pytestmark = pytest.mark.skipif(not seed_data.GRADES_EXT, reason="только с GRADES_EXT_ENABLED=1 (test_grades_ext.py)")

from app.core.db import SessionLocal  # noqa: E402
from app.modules.catalog import levels  # noqa: E402
from tests.conftest import register_and_verify  # noqa: E402
from tests.test_day2_rules import H, ONBOARDING  # noqa: E402

FAKE_BANK = {"backend": {"lead": ("backend.lead.a", "backend.lead.b"), "principal": ("backend.principal.a",)},
             "qa": {"lead": ("qa.lead.a",)},
             "common": {"lead": ("common.lead.a", "common.lead.b"), "principal": ("common.principal.a", "common.principal.b")}}


@pytest.fixture(autouse=True)
def fake_bank(monkeypatch):
    monkeypatch.setattr(levels, "bank_ext_families", lambda: FAKE_BANK)
    levels._available.cache_clear()
    yield
    levels._available.cache_clear()


def test_six_levels_and_visibility_by_bank():
    assert seed_data.GRADE_ORDER == ("intern", "junior", "middle", "senior", "lead", "principal")
    assert seed_data.GRADE_CUTS["lead"] == 2.0 and seed_data.GRADE_CUTS["principal"] == 3.0
    assert levels.available_grades("backend")[-2:] == ("lead", "principal")
    assert levels.available_grades("qa")[-1] == "lead"  # своих Principal нет — только Lead
    assert levels.available_grades("frontend")[-1] == "senior"  # своих нет — не видны
    assert levels.cap("frontend", "principal") == "senior" and levels.cap("qa", "principal") == "lead"
    st = levels.status(["backend", "frontend", "qa"])
    assert st["enabled"] and st["by_direction"]["frontend"]["grades"][-1] == "senior"
    assert st["by_direction"]["backend"]["families"] == {"lead": 2, "principal": 1}


def test_ceiling_lead_principal_only_full_test():
    from app.modules.assessment import grades

    assert grades.ceiling(10, 0.4, "backend") == "principal"
    assert grades.ceiling(6, 0.4, "backend") == "senior"     # меньше 8 заданий — не выше Senior
    assert grades.ceiling(12, 0.65, "backend") == "senior"   # погрешность больше 0,6
    assert grades.ceiling(10, 0.4, "frontend") == "senior"
    ok = grades.decide_grade(2.7, 0.3, "lead", n_items=12, direction="backend")
    assert ok.confirmed and ok.assigned == "lead"
    short = grades.decide_grade(2.7, 0.3, "lead", n_items=6, direction="backend")
    assert not short.confirmed and short.retake_lower == "senior"
    up = grades.decide_grade(2.8, 0.3, "senior", n_items=12, direction="backend")
    assert up.confirmed and up.upgrade_available  # Senior уверенно выше порога — можно пройти тест на Lead
    no_up = grades.decide_grade(2.8, 0.3, "senior", n_items=12, direction="frontend")
    assert no_up.confirmed and not no_up.upgrade_available  # в frontend Lead не проверяется


def test_need_parser_lead_principal_capped_by_bank():
    from app.modules.matching.need_parser import parse_rules

    r = parse_rules("Team Lead Python backend: FastAPI, PostgreSQL, Kafka; руководство командой из 6 человек")
    assert r["direction"] == "backend" and r["grade"] == "lead" and "grade_capped_from" not in r
    r = parse_rules("Principal engineer, backend на Go и PostgreSQL: архитектура платформы")
    assert r["grade"] == "principal"
    r = parse_rules("Тимлид frontend: React, TypeScript, ревью кода команды")
    assert r["direction"] == "frontend" and r["grade"] == "senior" and r["grade_capped_from"] == "lead"


def test_grade_hint_by_years_capped():
    from app.modules.assessment.grade_hint import grade_by_years

    assert grade_by_years(9, top="principal") == "lead" and grade_by_years(12, top="principal") == "principal"
    assert grade_by_years(12, top="lead") == "lead" and grade_by_years(12, top="senior") == "senior"
    assert grade_by_years(12, top=None) == "senior"  # направление неизвестно — Lead/Principal не подсказываем
    assert grade_by_years(3, top="principal") == "middle"


def test_meta_catalog_and_reference_rows(client):
    meta = client.get("/api/meta").json()
    ge = meta["grades_ext"]
    assert ge["enabled"] and ge["by_direction"]["backend"]["grades"][-1] == "principal"
    assert ge["by_direction"]["frontend"]["grades"][-1] == "senior"
    cat = client.get("/api/catalog").json()
    ids = {c["id"] for c in cat["categories"]}
    assert {"backend.lead", "backend.principal", "qa.lead"} <= ids
    assert not ({"frontend.lead", "qa.principal"} & ids)
    assert [g["id"] for g in cat["grades"]][-2:] == ["lead", "principal"]
    lead = next(c for c in cat["categories"] if c["id"] == "backend.lead")
    assert lead["title"] == "Backend · Lead"


def test_start_session_lead_only_where_bank_checks(client):
    token = register_and_verify(client)
    r = client.put("/api/me/onboarding", headers=H(token),
                   json={**ONBOARDING, "experience_years": 9, "additional_direction": "frontend",
                         "additional_stack": [{"tag": "javascript", "level": 3}]})
    assert r.status_code == 200, r.text
    r = client.post("/api/assessment/sessions", headers=H(token), json={"claimed_grade": "lead", "direction": "frontend"})
    assert r.status_code == 422 and "grade_unavailable" in r.text
    st = client.get("/api/assessment/status?direction=frontend", headers=H(token)).json()
    assert st["grades"][-1] == "senior" and st["grades_hidden"] == ["lead", "principal"]
    st = client.get("/api/assessment/status?direction=backend", headers=H(token)).json()
    assert st["grades"][-1] == "principal" and st["grades_titles"]["lead"] == "Lead"
    r = client.post("/api/assessment/sessions", headers=H(token), json={"claimed_grade": "lead", "direction": "backend"})
    assert r.status_code == 201, r.text


def test_demo_lead_principal_model_candidates(client):
    from app.modules.auth.models import User
    from app.modules.demo.seed import EXT_FIRST, ext_candidates
    from app.modules.profiles.models import CandidateProfile

    with SessionLocal() as db:
        added = ext_candidates(db, 20261007, "x", set())
        db.commit()
        assert added == 5 + 3  # backend: 3 Lead + 2 Principal; qa: 3 Lead; frontend и прочие — нет
        profs = db.scalars(select(CandidateProfile).where(CandidateProfile.current_grade_id.in_(("lead", "principal")))).all()
        assert len(profs) == 8 and all("модель, не люди" in (p.about or "") for p in profs)
        assert {p.current_category_id for p in profs} == {"backend.lead", "backend.principal", "qa.lead"}
        emails = set(db.scalars(select(User.email).where(User.email.like("demo-candidate-%@demo.invalid"))))
        assert min(int(e[15:18]) for e in emails) >= EXT_FIRST
        assert ext_candidates(db, 20261007, "x", emails) == 0  # идемпотентно
