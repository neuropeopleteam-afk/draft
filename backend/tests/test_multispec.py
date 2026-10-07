"""И14: два независимых направления, доказательства и совместимость старой категории."""
from datetime import timedelta
import io
import uuid

from sqlalchemy import select

from app.core.db import SessionLocal, as_aware, utcnow
from app.modules.assessment.models import TestSession as AssessmentSession
from app.modules.profiles.models import CandidateFact, CandidateProfile, CandidateSpecialization
from tests.conftest import register_and_verify
from tests.test_day2_rules import H, ONBOARDING, correct_index, employer, my_ref


def survey(client, token, **extra):
    r = client.put("/api/me/onboarding", headers=H(token), json={**ONBOARDING, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def dual(client):
    token = register_and_verify(client)
    survey(client, token, additional_direction="frontend", additional_stack=[{"tag": "javascript", "level": 2}])
    return token


def finish(client, token, direction, grade="middle", correct=True):
    r = client.post("/api/assessment/sessions", headers=H(token),
                    json={"claimed_grade": grade, "direction": direction})
    assert r.status_code == 201, r.text
    s = r.json()
    while s["item"]:
        it = s["item"]
        answer = correct_index(s["session_id"], it["item_id"])
        if not correct:
            answer = (answer + 1) % len(it["options"])
        r = client.post(f"/api/assessment/sessions/{s['session_id']}/answers", headers=H(token),
                        json={"item_id": it["item_id"], "answer": answer})
        assert r.status_code == 200, r.text
        s = r.json()
    r = client.post(f"/api/assessment/sessions/{s['session_id']}/finish", headers=H(token))
    assert r.status_code == 200, r.text
    return r.json()


def test_two_tests_independent_locks_and_legacy_profile(client):
    token = dual(client)
    first = finish(client, token, "backend")
    p1 = client.get("/api/me", headers=H(token)).json()["candidate"]
    second = finish(client, token, "frontend", "junior")
    assert second["confirmed"] and second["category_id"] == "frontend.junior" and not second["is_primary"]
    p2 = client.get("/api/me", headers=H(token)).json()["candidate"]
    assert p2["current_category_id"] == p1["current_category_id"] == "backend.middle"
    assert p2["grade_locked_until"] == p1["grade_locked_until"]
    assert p2["rating_score"] == p1["rating_score"]
    status = client.get("/api/assessment/status?direction=frontend", headers=H(token)).json()
    assert status["current"]["category_id"] == "frontend.junior"
    assert len(status["specializations"]) == len(status["grade_history"]) == 2
    for direction in ("backend", "frontend"):
        r = client.post("/api/assessment/sessions", headers=H(token),
                        json={"direction": direction, "claimed_grade": "senior"})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "grade_locked"
    # Повтор finish идемпотентен и относится к своему направлению.
    assert client.post(f"/api/assessment/sessions/{first['session_id']}/finish", headers=H(token)).json() == first
    assert client.post(f"/api/assessment/sessions/{second['session_id']}/finish", headers=H(token)).json() == second


def test_direction_specific_facts_search_selection_compare_and_pdf(client):
    from pypdf import PdfReader

    token = dual(client)
    finish(client, token, "backend")
    finish(client, token, "frontend", "junior")
    hr = employer(client)
    ref = my_ref(client, token)
    rows = client.get("/api/employer/candidates?direction=frontend&grade=junior", headers=H(hr))
    assert rows.status_code == 200, rows.text
    card = rows.json()["items"][0]
    assert card["category"]["id"] == "frontend.junior" and len(card["specializations"]) == 2
    assert all(s["confirmed_by"] == "test" for s in card["specializations"])
    assert card["test"]["engine"] and card["grade"] == "junior"
    counts = client.get("/api/employer/categories", headers=H(hr)).json()
    assert {c["id"]: c["count"] for c in counts}["frontend.junior"] == 1
    assert client.get("/api/employer/candidates", headers=H(hr)).json()["total"] == 1
    another = register_and_verify(client, email="frontend@example.com")
    survey(client, another, direction="frontend", stack=[{"tag": "javascript", "level": 2}])
    finish(client, another, "frontend", "junior")
    ref2 = my_ref(client, another)
    r = client.post("/api/employer/needs", headers=H(hr), json={"text": "Нужен frontend junior, JavaScript, 100–140 тыс."})
    assert r.status_code == 201, r.text
    need = r.json()
    selection = client.get(f"/api/employer/needs/{need['id']}/selections/1", headers=H(hr)).json()
    assert selection["results"][0]["category_id"] == "frontend.junior"
    comparison = client.get(f"/api/employer/needs/{need['id']}/compare?refs={ref}&refs={ref2}", headers=H(hr))
    assert comparison.status_code == 200, comparison.text
    cells = comparison.json()["candidates"][0]["cells"]
    assert "Frontend" in cells["category"]["text"]
    assert "Backend" in cells["specializations"]["text"] and "Frontend" in cells["specializations"]["text"]
    detail = client.get(f"/api/employer/candidates/{ref}?need_id={need['id']}", headers=H(hr)).json()
    assert detail["category"]["id"] == "frontend.junior"
    pdf = client.get(f"/api/employer/candidates/{ref}/profile.pdf", headers=H(hr))
    assert pdf.status_code == 200
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Backend" in text and "Frontend" in text and "отдельным тестом" in text
    assert "Иван" not in text and "cand@example.com" not in text
    detail_by_direction = client.get(f"/api/employer/candidates/{ref}?direction=frontend", headers=H(hr)).json()
    assert detail_by_direction["category"]["id"] == "frontend.junior"
    from tests.test_day2_rules import INVITE

    invitation = client.post("/api/employer/invitations", headers=H(hr),
                             json={**INVITE, "candidate_ref": ref, "need_id": need["id"]}).json()
    evidence = next(x for x in invitation["evidence"] if x["kind"] == "test")
    assert "Frontend" in evidence["text"] and "Backend" not in evidence["text"]
    with SessionLocal() as db:
        uid = db.scalar(select(CandidateProfile.user_id).where(CandidateProfile.public_ref == ref))
        facts = list(db.scalars(select(CandidateFact).where(CandidateFact.kind == "test_result", CandidateFact.user_id == uid)))
        assert {f.value["direction"] for f in facts} == {"backend", "frontend"}


def test_untested_secondary_not_in_search_and_failed_test_cannot_replace_primary(client):
    token = dual(client)
    first = finish(client, token, "backend")
    failed = finish(client, token, "frontend", correct=False)
    assert not failed["confirmed"] and failed["category_id"] is None
    assert client.get("/api/me", headers=H(token)).json()["candidate"]["current_category_id"] == "backend.middle"
    hr = employer(client)
    assert client.get("/api/employer/candidates?direction=frontend", headers=H(hr)).json()["total"] == 0
    card = client.get("/api/employer/candidates?direction=backend", headers=H(hr)).json()["items"][0]
    assert card["test"]["theta"] == first["theta"]
    assert {x["status"] for x in card["specializations"]} == {"declared", "confirmed"}


def test_parallel_active_sessions_in_different_directions(client):
    token = dual(client)
    sessions = {}
    for direction in ("backend", "frontend"):
        r = client.post("/api/assessment/sessions", headers=H(token), json={"direction": direction, "claimed_grade": "middle"})
        assert r.status_code == 201
        sessions[direction] = r.json()["session_id"]
    assert len(set(sessions.values())) == 2
    for direction, sid in sessions.items():
        assert client.get(f"/api/assessment/sessions/{sid}", headers=H(token)).json()["status"] == "in_progress"
        assert client.post("/api/assessment/sessions", headers=H(token),
                           json={"direction": direction, "claimed_grade": "middle"}).json()["session_id"] == sid
    other = register_and_verify(client, email="other@example.com")
    assert client.get(f"/api/assessment/sessions/{sessions['frontend']}", headers=H(other)).status_code == 404


def test_two_direction_limit_and_distinct_validation(client):
    token = dual(client)
    assert client.put("/api/me/onboarding", headers=H(token),
                      json={**ONBOARDING, "additional_direction": "backend"}).status_code == 422
    r = client.put("/api/me/onboarding", headers=H(token),
                   json={**ONBOARDING, "additional_direction": "qa"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "specialization_limit"
    r = client.post("/api/assessment/sessions", headers=H(token), json={"direction": "security", "claimed_grade": "middle"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "onboarding_required"
    onb = client.get("/api/me/onboarding", headers=H(token)).json()["answers"]
    assert onb["direction"] == "backend" and onb["additional_direction"] == "frontend"
    assert onb["additional_stack"] == [{"tag": "javascript", "level": 2}]


def test_secondary_can_be_confirmed_before_primary_and_invited(client):
    from tests.test_day2_rules import INVITE

    token = dual(client)
    finish(client, token, "frontend", "junior")
    assert client.get("/api/me", headers=H(token)).json()["candidate"]["current_category_id"] is None
    hr = employer(client)
    card = client.get("/api/employer/candidates?direction=frontend", headers=H(hr)).json()["items"][0]
    ref = card["ref"]
    assert card["category"]["id"] == "frontend.junior"
    assert client.get(f"/api/employer/candidates/{ref}", headers=H(hr)).status_code == 200
    r = client.post("/api/employer/invitations", headers=H(hr), json={**INVITE, "candidate_ref": ref})
    assert r.status_code == 201, r.text


def test_retest_only_updates_its_direction(client):
    token = dual(client)
    finish(client, token, "backend")
    second = finish(client, token, "frontend", "junior")
    with SessionLocal() as db:
        row = db.scalar(select(CandidateSpecialization).where(CandidateSpecialization.direction_id == "frontend"))
        row.locked_until = utcnow() - timedelta(days=1)
        db.commit()
    finish(client, token, "frontend", "middle")
    s = client.get("/api/assessment/status", headers=H(token)).json()
    assert s["current"]["category_id"] == "backend.middle"
    histories = {x["direction"]: x["grade_history"] for x in s["specializations"]}
    assert len(histories["backend"]) == 1 and len(histories["frontend"]) == 2
    assert histories["frontend"][1]["from"] is None
    assert histories["frontend"][0]["from"] == "junior"
    with SessionLocal() as db:
        facts = list(db.scalars(select(CandidateFact).where(CandidateFact.kind == "test_result")))
        assert len(facts) == 2 and {f.key for f in facts} == {"backend.middle", "frontend.middle"}
        front = db.scalar(select(CandidateSpecialization).where(CandidateSpecialization.direction_id == "frontend"))
        assert as_aware(front.locked_until) > as_aware(db.get(AssessmentSession, uuid.UUID(second["session_id"])).finished_at)


def test_migration_backfill_preserves_data_and_downgrade(engine, tmp_path):
    from alembic import command
    import sqlalchemy as sa
    from sqlalchemy.orm import Session

    from app.core.enums import EvidenceLevel, FactSource, UserRole
    from app.modules.assessment.models import GradeHistory, SurveyResponse
    from app.modules.auth.models import User
    from tests.conftest import alembic_config

    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "qr01")
    legacy_engine = sa.create_engine(url)
    until = utcnow() + timedelta(days=60)
    # Строки собираются моделями текущей схемы во временной базе и переносятся в базу qr01 только теми колонками,
    # которые там есть: тест не ломается от новых полей других миграций (fs01 и далее).
    from app.core.db import Base
    head_engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(head_engine)
    with Session(head_engine) as db:
        old = User(email="legacy@example.com", role=UserRole.candidate, password_hash="test", is_email_verified=True)
        fresh = User(email="untested@example.com", role=UserRole.candidate, password_hash="test", is_email_verified=True)
        db.add_all([old, fresh])
        db.flush()
        uid, fresh_id = old.id, fresh.id
        db.add_all([
            CandidateProfile(user_id=uid, current_direction_id="backend", current_grade_id="middle",
                             current_category_id="backend.middle", rating_score=0.73, grade_locked_until=until),
            CandidateProfile(user_id=fresh_id, onboarding_completed_at=utcnow()),
            CandidateFact(user_id=uid, kind="test_result", key="backend.middle", title="Тест", value={"theta": 0.7, "se": 0.3},
                          evidence_level=EvidenceLevel.T1, source=FactSource.test),
            SurveyResponse(user_id=fresh_id, direction_id="qa", claimed_grade_id="junior"),
            GradeHistory(user_id=uid, direction_id="backend", to_grade_id="middle", reason="initial", locked_until=until),
        ])
        db.commit()
    legacy_meta = sa.MetaData()
    legacy_meta.reflect(legacy_engine)
    with head_engine.connect() as src, legacy_engine.begin() as dst:
        for model in (User, CandidateProfile, CandidateFact, SurveyResponse, GradeHistory):
            name = model.__table__.name
            cols = [c.name for c in legacy_meta.tables[name].columns]
            raw = src.exec_driver_sql(f"SELECT * FROM {name}").mappings()  # значения как в базе, без типов моделей
            for r in raw:
                keys = [k for k in cols if k in r]
                dst.exec_driver_sql(f"INSERT INTO {name} ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                                    tuple(r[k] for k in keys))
    head_engine.dispose()
    command.upgrade(cfg, "ms01")
    with Session(legacy_engine) as db:
        row = db.get(CandidateSpecialization, (uid, "backend"))
        assert row.is_primary and row.status == "confirmed" and row.category_id == "backend.middle"
        assert row.theta == 0.7 and row.theta_se == 0.3 and row.rating_score == 0.73
        assert abs((as_aware(row.locked_until) - until).total_seconds()) < 1
        pending = db.get(CandidateSpecialization, (fresh_id, "qa"))
        assert pending.is_primary and pending.status == "declared" and pending.grade_id is None
        assert len(list(db.scalars(select(GradeHistory)))) == 1
    command.downgrade(cfg, "qr01")
    assert "candidate_specializations" not in sa.inspect(legacy_engine).get_table_names()
    with legacy_engine.connect() as conn:
        cat = conn.exec_driver_sql("SELECT current_category_id FROM candidate_profiles WHERE user_id = ?",
                                   (uid.hex if hasattr(uid, "hex") else uid,)).scalar()
        assert cat == "backend.middle"
    legacy_engine.dispose()


def test_secondary_facts_do_not_leak_to_primary_scoring(client):
    from app.modules.matching.ranking import score_candidate
    from app.modules.profiles.facts import load_bundles

    token = dual(client)
    finish(client, token, "backend")
    finish(client, token, "frontend", "junior")
    ref = my_ref(client, token)
    with SessionLocal() as db:
        p = db.scalar(select(CandidateProfile).where(CandidateProfile.public_ref == ref))
        backend = load_bundles(db, [p.user_id], direction="backend")[p.user_id]
        frontend = backend.for_direction("frontend")
        assert "javascript" in frontend.skills_t1 and "javascript" not in backend.skills_t1
        assert backend.test.key == "backend.middle" and frontend.test.key == "frontend.junior"
        req = {"direction": "backend", "grade": "middle", "stack_required": [{"tag": "javascript", "weight": 1}]}
        _, components, _ = score_candidate(backend, req)
        assert components["stack_required"] == 0
        fb = client.get("/api/assessment/feedback?session_id=" + frontend.test.value["session_id"], headers=H(token)).json()
        assert fb["session"]["category_id"] == "frontend.junior" and fb["session"]["direction"] == "frontend"


def test_probes_do_not_transfer_to_another_direction(client):
    from app.core.enums import EvidenceLevel, FactSource
    from app.modules.profiles.facts import load_bundles

    token = dual(client)
    finish(client, token, "backend")
    finish(client, token, "frontend", "junior")
    ref = my_ref(client, token)
    with SessionLocal() as db:
        p = db.scalar(select(CandidateProfile).where(CandidateProfile.public_ref == ref))
        db.add(CandidateFact(user_id=p.user_id, kind="probe", key="backend-probe", title="Зонд Backend",
                            value={"direction": "backend", "score": 1}, evidence_level=EvidenceLevel.T1, source=FactSource.probe))
        # Старый зонд без направления относится к основному направлению, а не к любому.
        db.add(CandidateFact(user_id=p.user_id, kind="probe", key="legacy-probe", title="Старый зонд",
                            value={"score": 1}, evidence_level=EvidenceLevel.T1, source=FactSource.probe))
        db.commit()
        b = load_bundles(db, [p.user_id])[p.user_id]
        assert len(b.for_direction("backend").probes_t1) == 2
        assert not b.for_direction("frontend").probes_t1
