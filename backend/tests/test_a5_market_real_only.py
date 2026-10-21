"""Рыночный режим в подборе (находка А12, 21.10): демо- и синтетические профили не попадают в подборку и поиск
настоящего работодателя; демо-персоны и жюри по-прежнему видят демо (подборка жюри, «Демо для жюри»).

Путь — как у пользователя: настоящий кандидат и два «демо» (синтетический профиль и учётка-демо) проходят тест
Middle; настоящий работодатель описывает потребность → версия подборки 1; поиск /employer/candidates; карточка
кандидата — место в категории считается только среди настоящих. Значение по умолчанию — jury_scope.real_default (А1).
"""
import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.assessment import engine as em
from tests.conftest import register_and_verify
from tests.test_day2_rules import ONBOARDING, H, employer, pass_test


@pytest.fixture
def theta(monkeypatch):
    monkeypatch.setattr(em, "eap_theta", lambda responses: (0.5, 0.3))


def _candidate(client, email: str) -> tuple[str, str]:
    t = register_and_verify(client, email=email)
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    assert pass_test(client, t, "middle")["confirmed"]
    return t, client.get("/api/me", headers=H(t)).json()["candidate"]["public_ref"]


def _mark(email: str, *, synthetic: bool = False, demo: bool = False) -> None:
    from app.modules.auth.models import User
    from app.modules.profiles.models import CandidateProfile

    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        if demo:
            u.is_demo = True
        if synthetic:
            db.get(CandidateProfile, u.id).is_synthetic = True
        db.commit()


def _world(client):
    _, real = _candidate(client, "market-real@example.com")
    _, syn = _candidate(client, "market-syn@example.com")
    _, demo = _candidate(client, "market-demo@example.com")
    _mark("market-syn@example.com", synthetic=True)
    _mark("market-demo@example.com", demo=True)
    # учётка жюри в базе (как на стенде): real_default не уходит в запасной режим «база без жюри — показывать всех»
    register_and_verify(client, email="employer@jury.example.com", role="employer", company_name="Демо жюри")
    _mark("employer@jury.example.com", demo=True)
    return {"real": real, "syn": syn, "demo": demo}


NEED = {"text": "Ищем бэкенд-разработчика middle: обязательно Python и PostgreSQL. Удалённо, 200–280 тыс."}


def test_real_employer_selection_and_search_have_no_demo_profiles(client, theta):
    w = _world(client)
    e = employer(client, email="hr-market@corp.ru", company="ООО Настоящая")
    need = client.post("/api/employer/needs", json=NEED, headers=H(e))
    assert need.status_code in (200, 201), need.text
    v1 = client.get(f"/api/employer/needs/{need.json()['id']}/selections/1", headers=H(e)).json()
    refs = {r["ref"] for r in v1["results"]}
    assert w["real"] in refs, "настоящий кандидат с подтверждённым Middle должен быть в подборке"
    assert w["syn"] not in refs and w["demo"] not in refs, f"демо в подборке настоящего работодателя: {refs}"
    # «Обновить подборку» с фильтрами по умолчанию — то же правило
    r = client.post(f"/api/employer/needs/{need.json()['id']}/selections", json={}, headers=H(e))
    assert r.status_code in (200, 201), r.text
    refs2 = {x["ref"] for x in r.json()["results"]}
    assert w["real"] in refs2 and not ({w["syn"], w["demo"]} & refs2)
    # поиск по направлению и счётчики категорий
    s = client.get("/api/employer/candidates", params={"direction": "backend"}, headers=H(e)).json()
    srefs = {c["ref"] for c in s["items"]}
    assert w["real"] in srefs and not ({w["syn"], w["demo"]} & srefs)
    cats = {c["id"]: c for c in client.get("/api/employer/categories", headers=H(e)).json()}
    assert cats["backend.middle"]["count"] == 1  # только настоящий
    # карточка: место в категории — среди настоящих (1 из 1), демо не входят в «из N»
    card = client.get(f"/api/employer/candidates/{w['real']}", headers=H(e)).json()
    assert (card["rank_in_category"], card["category_size"]) == (1, 1), card
    # в поиске — то же «место в категории»: 1 из 1
    item = next(c for c in s["items"] if c["ref"] == w["real"])
    assert (item["rank_in_category"], item["category_size"]) == (1, 1), item


def test_demo_persona_still_sees_demo_pool(client, theta):
    """Жюри и демо-персоны видят демо-профили: «Демо для жюри» не ломается."""
    w = _world(client)
    tok = employer(client, email="hr-demo@corp.ru", company="ООО Демо-персона")
    _mark("hr-demo@corp.ru", demo=True)  # демо-персона (users.is_demo) — как работодатель из «Демо для жюри»
    s = client.get("/api/employer/candidates", params={"direction": "backend"}, headers=H(tok)).json()
    srefs = {c["ref"] for c in s["items"]}
    assert {w["real"], w["syn"], w["demo"]} <= srefs, srefs
    card = client.get(f"/api/employer/candidates/{w['real']}", headers=H(tok)).json()
    assert card["category_size"] == 3, card  # демо-персона считает место среди всего демо-пула
    # и явный real_only=true у демо-персоны — тоже работает (переключатель «только настоящие»)
    s2 = client.get("/api/employer/candidates", params={"direction": "backend", "real_only": "true"},
                    headers=H(tok)).json()
    assert {c["ref"] for c in s2["items"]} == {w["real"]}
