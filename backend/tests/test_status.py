"""Единая модель статуса грейда: подтверждён / предварительно / не подтверждён.

Кандидат без подтверждённого грейда (опрос пройден, теста нет или он не подтвердил заявленный грейд) виден
работодателю со статусом «грейд не подтверждён (заявлен …)», в поиске и подборке — всегда ниже подтверждённых,
фильтр «только подтверждённые» убирает его; карточка, сравнение, PDF и объяснение «почему» несут тот же статус.
"""
from types import SimpleNamespace

import pytest

from app.core.db import utcnow
from app.modules.assessment import engine as em
from tests.conftest import register_and_verify
from tests.test_day2_rules import ONBOARDING, H, employer, pass_test


@pytest.fixture
def theta(monkeypatch):
    box = {"v": (0.5, 0.3)}
    monkeypatch.setattr(em, "eap_theta", lambda responses: box["v"])
    return box


def _onboard(client, email, **extra):
    t = register_and_verify(client, email=email)
    assert client.put("/api/me/onboarding", json={**ONBOARDING, **extra}, headers=H(t)).status_code == 200
    return t


def _ref(client, t):
    return client.get("/api/me", headers=H(t)).json()["candidate"]["public_ref"]


# ---------------------------------------------------------------- модель статуса (без БД)

def _bundle(category, grade, provisional=False, test=True, survey=None, attempt=None):
    from app.modules.profiles.facts import Bundle

    p = SimpleNamespace(current_direction_id=category.split(".")[0] if category else None, current_grade_id=grade,
                        current_category_id=category, grade_provisional=provisional, work_format=None, privacy={},
                        rating_score=None, public_ref="K-TEST")
    t = SimpleNamespace(value={"theta": -0.9, "se": 0.4, "correct": 10, "answered": 18,
                              **({"provisional": {"p": 0.31, "p_pct": 31, "reason": "uncertain",
                                                  "text": "Junior предварительно"}} if provisional else {})},
                        created_at=utcnow()) if test else None
    return Bundle(profile=p, test=t, survey=survey, last_attempt=attempt)


def test_grade_status_three_states():
    from app.modules.profiles.facts import grade_status

    s = grade_status(_bundle("backend.middle", "middle"))
    assert (s["status"], s["title"], s["tier"]) == ("confirmed", "подтверждён", 0)
    s = grade_status(_bundle("backend.junior", "junior", provisional=True))
    assert (s["status"], s["tier"], s["p_pct"]) == ("provisional", 0, 31)
    sv = SimpleNamespace(direction_id="backend", claimed_grade_id="middle")
    s = grade_status(_bundle(None, None, test=False, survey=sv))
    assert s["status"] == "unconfirmed" and s["tier"] == 1 and s["claimed_category_id"] == "backend.middle"
    assert "заявлен Middle" in s["text"] and "тест не пройден" in s["text"]
    at = SimpleNamespace(claimed_grade_id="middle", direction_id="backend", theta=-1.7, theta_se=0.31, finished_at=utcnow())
    s = grade_status(_bundle(None, None, test=False, survey=sv, attempt=at))
    assert "не подтвердил грейд" in s["text"] and s["attempt"]["theta"] == -1.7 and s["attempt"]["se"] == 0.31
    # заявленных грейдов может быть больше трёх — заголовок берётся из каталога, а не из жёсткого списка
    assert s["claimed_title"] == "Backend · Middle"


def test_tier_order_in_ranking():
    from app.modules.matching import ranking

    assert ranking.tier(_bundle("backend.middle", "middle")) == 0
    assert ranking.tier(_bundle("backend.junior", "junior", provisional=True)) == 0
    assert ranking.tier(_bundle(None, None, test=False)) == 1
    req = {"direction": "backend", "grade": "middle", "stack_required": [{"tag": "python", "weight": 1.0}]}
    s, comps, reasons = ranking.score_candidate(_bundle(None, None, test=False,
                                                        survey=SimpleNamespace(direction_id="backend",
                                                                               claimed_grade_id="middle")), req)
    assert comps["test"] == 0 and comps["grade_status"] == "unconfirmed"
    assert reasons[0]["level"] == "T0" and reasons[0]["status"] == "unconfirmed" and "не подтверждён" in reasons[0]["text"]


# ---------------------------------------------------------------- через API

def test_unconfirmed_visible_below_confirmed_and_filterable(client, theta):
    # подтверждённый Middle, Junior (предварительно), «не подтверждён» без теста и «не подтверждён» после провала
    t_mid = _onboard(client, "mid@example.com")
    theta["v"] = (0.5, 0.3)
    assert pass_test(client, t_mid, "middle")["confirmed"]
    t_jun = _onboard(client, "jun@example.com", experience_years=1)
    theta["v"] = (-1.2, 0.4)
    r = pass_test(client, t_jun, "junior")
    assert r["category_provisional"]
    t_none = _onboard(client, "none@example.com")                      # опрос есть, теста нет
    t_fail = _onboard(client, "fail@example.com")                      # заявил Middle, тест не подтвердил
    theta["v"] = (-1.8, 0.3)
    r = pass_test(client, t_fail, "middle")
    assert not r["confirmed"] and r["category_id"] is None

    e = employer(client)
    found = client.get("/api/employer/candidates", params={"direction": "backend"}, headers=H(e)).json()
    assert found["total"] == 4 and found["confirmed"] == 1 and found["provisional"] == 1 and found["unconfirmed"] == 2
    statuses = [c["status"]["status"] for c in found["items"]]
    assert statuses[:2] == ["confirmed", "provisional"] and statuses[2:] == ["unconfirmed", "unconfirmed"]
    unc = {c["ref"]: c for c in found["items"] if c["status"]["status"] == "unconfirmed"}
    c_none, c_fail = unc[_ref(client, t_none)], unc[_ref(client, t_fail)]
    assert c_none["category"] is None and c_none["claimed"]["category_id"] == "backend.middle"
    assert "заявлен Middle" in c_none["status"]["text"] and "тест не пройден" in c_none["status"]["text"]
    assert "не подтвердил грейд" in c_fail["status"]["text"] and c_fail["status"]["attempt"]["theta"] == -1.8
    assert c_none["market_range"] is None and c_none["test"] is None and c_none["rank_in_category"] is None
    for secret in ("none@example.com", "Иван", "250000"):
        assert secret not in str(c_none)

    # фильтр по заявленному грейду и только подтверждённые
    assert client.get("/api/employer/candidates", params={"grade": "middle"}, headers=H(e)).json()["total"] == 3
    assert client.get("/api/employer/candidates", params={"grade": "junior"}, headers=H(e)).json()["total"] == 1
    only = client.get("/api/employer/candidates", params={"direction": "backend", "confirmed": True}, headers=H(e)).json()
    assert only["total"] == 1 and only["items"][0]["status"]["status"] == "confirmed"
    cats = {c["id"]: c for c in client.get("/api/employer/categories", headers=H(e)).json()}
    assert cats["backend.middle"]["count"] == 1 and cats["backend.middle"]["unconfirmed"] == 2
    assert cats["backend.junior"]["provisional"] == 1 and cats["backend.junior"]["unconfirmed"] == 0

    # карточка и PDF доступны: тот же статус; зонд/приглашение не закрыты
    d = client.get(f"/api/employer/candidates/{c_fail['ref']}", headers=H(e)).json()
    assert d["status"]["status"] == "unconfirmed" and d["can_invite"] and d["rank_in_category"] is None
    pdf = client.get(f"/api/employer/candidates/{c_fail['ref']}/profile.pdf", headers=H(e))
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    # подборка: не подтверждённые — отдельным ярусом ниже, даже при лучшем совпадении стека
    need = client.post("/api/employer/needs", json={
        "text": "Ищем бэкенд-разработчика middle: обязательно Python и PostgreSQL. Удалённо, 200–280 тыс."},
        headers=H(e)).json()
    v1 = client.get(f"/api/employer/needs/{need['id']}/selections/1", headers=H(e)).json()
    assert v1["total"] == 3 and v1["confirmed_matched"] == 1 and v1["unconfirmed_matched"] == 2
    assert [r["grade_status"] for r in v1["results"]] == ["confirmed", "unconfirmed", "unconfirmed"]
    assert v1["results"][0]["rank"] == 1 and v1["results"][1]["card"]["status"]["status"] == "unconfirmed"
    why = v1["results"][1]["reasons"][0]
    assert why["level"] == "T0" and why["status"] == "unconfirmed"
    cat = next(c for c in v1["categories"] if c["id"] == "backend.middle")
    assert cat["unconfirmed"] == 2
    v2 = client.post(f"/api/employer/needs/{need['id']}/selections",
                     json={"parent_version": 1, "filters": {"confirmed_only": True}}, headers=H(e)).json()
    assert v2["total"] == 1 and v2["unconfirmed_matched"] == 0 and v2["results"][0]["grade_status"] == "confirmed"

    # сравнение: ячейка категории несёт статус «не подтверждён», θ последней попытки — T0
    refs = [v1["results"][0]["ref"], c_fail["ref"]]
    cmp_ = client.get(f"/api/employer/needs/{need['id']}/compare", params={"refs": refs}, headers=H(e)).json()
    cells = {c["ref"]: c["cells"] for c in cmp_["candidates"]}
    assert cells[c_fail["ref"]]["category"]["status"] == "unconfirmed" and cells[c_fail["ref"]]["theta"]["level"] == "T0"
    assert next(c for c in cmp_["candidates"] if c["ref"] == c_fail["ref"])["status"]["status"] == "unconfirmed"

    # кандидат видит тот же статус у себя
    st = client.get("/api/assessment/status", headers=H(t_fail)).json()
    assert st["grade_status"]["status"] == "unconfirmed" and st["grade_status"]["claimed_grade"] == "middle"
    assert client.get("/api/assessment/status", headers=H(t_mid)).json()["grade_status"]["status"] == "confirmed"
    assert client.get("/api/assessment/status", headers=H(t_jun)).json()["grade_status"]["status"] == "provisional"

    # снятие согласия на публикацию скрывает и не подтверждённого
    assert client.delete("/api/me/consents/publication", headers=H(t_none)).status_code == 200
    assert client.get("/api/employer/candidates", params={"direction": "backend"}, headers=H(e)).json()["total"] == 3
    assert client.get(f"/api/employer/candidates/{c_none['ref']}", headers=H(e)).status_code == 404


def test_unconfirmed_without_survey_not_listed(client):
    """Регистрация без опроса — кандидата в базе работодателя нет (заявлять нечего)."""
    register_and_verify(client, email="raw@example.com")
    e = employer(client)
    assert client.get("/api/employer/candidates", headers=H(e)).json()["total"] == 0


# ---------------------------------------------------------------- демо-данные и персона жюри

def test_demo_seed_status_variants_do_not_shift_main_candidates(client):
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.modules.auth.models import User
    from app.modules.demo.seed import PROVISIONAL_DEMO, UNCONFIRMED_DEMO, seed
    from app.modules.matching import ranking
    from app.modules.profiles.models import CandidateProfile
    from app.modules.validation.matching_eval import pick_set
    from app.modules.profiles.facts import load_bundles

    with SessionLocal() as db:
        out = seed(db)
        assert out["candidates"] == 150 + len(PROVISIONAL_DEMO) + len(UNCONFIRMED_DEMO)
        rows = db.execute(select(User.email, CandidateProfile.full_name, CandidateProfile.current_category_id,
                                 CandidateProfile.grade_provisional)
                          .join(CandidateProfile, CandidateProfile.user_id == User.id)
                          .where(User.email.like("demo-candidate-%")).order_by(User.email)).all()
        main = [r for r in rows if r[0] <= "demo-candidate-150@demo.invalid"]
        assert len(main) == 150 and all(r[2] and not r[3] for r in main)
        # первый основной кандидат — тот же, что и до добавления статусов (отдельные генераторы Random(seed+1/+2))
        assert main[0][1] == "Мария Павлова" and main[0][2] == "backend.junior"
        assert main[-1][1] == "Ольга Киселёва" and main[-1][2] == "security.senior"
        prov = [r for r in rows if r[3]]
        assert len(prov) == 5 and {r[2] for r in prov} == {f"{d}.junior" for d, _ in PROVISIONAL_DEMO}
        unc = ranking.unconfirmed_counts(db)
        assert sum(unc.values()) == len(UNCONFIRMED_DEMO) and unc["backend.middle"] == 1
        # в набор для разметки подбора предварительные и неподтверждённые не попадают
        ids = [db.scalar(select(User.id).where(User.email == r[0])) for r in rows]
        bundles = list(load_bundles(db, ids).values())
        import random
        picked = pick_set(bundles, {"direction": "backend", "grade": "junior"}, random.Random(1))
        assert picked and all(b.profile.current_category_id and not b.provisional for b in picked)

    e = employer(client)
    found = client.get("/api/employer/candidates", params={"direction": "backend", "grade": "junior"}, headers=H(e)).json()
    assert found["provisional"] == 1 and found["unconfirmed"] == 1 and found["total"] == 12
    assert [c["status"]["status"] for c in found["items"]][-1] == "unconfirmed"


def test_jury_persona_candidate_junior(client):
    r = client.get("/api/jury/status")
    assert any(p["id"] == "candidate_junior" and p["role"] == "candidate" for p in r.json()["personas"])
    r = client.post("/api/jury/login", json={"persona": "candidate_junior"})
    assert r.status_code == 200, r.text
    assert r.json()["landing"] == "/candidate/category"
    tok = r.json()["access_token"]
    me = client.get("/api/me", headers=H(tok)).json()
    assert me["email"] == "candidate-junior@jury.example.com" and me["candidate"]["current_category_id"] == "backend.junior"
    st = client.get("/api/assessment/status", headers=H(tok)).json()
    assert st["current"]["provisional"] and st["grade_status"]["status"] == "provisional"
    assert st["provisional"]["attempts_left"] == 2 and st["claimed_grade"] == "junior"
