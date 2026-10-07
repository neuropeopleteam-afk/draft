"""Матрица прав доступа: ВСЕ маршруты приложения × роли (И15а, п. 1).

Политики — tests/security_policy.py (там же инструкция, как дополнять). Обход маршрутов — tests/route_walk.py
(FastAPI 0.142: вложенные роутеры). Маршрут без политики роняет тест с готовой строкой для вставки.

Мир теста: «настоящие» кандидат C1 (с категорией), работодатели E1 (владелец объектов) и E2 (другая компания),
админ, аналитик ФСП, эксперт; песочница жюри A (кандидат, работодатель, эксперт, аналитик) с собственными объектами
и песочница B (работодатель и кандидат) — для неё объекты и кандидаты песочницы A не должны существовать.
Для каждого маршрута запрос делается каждой ролью: учётки песочниц работают с объектами стороны A, остальные —
со стороной «настоящих» пользователей. Все расхождения собираются и печатаются разом.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import io
import re
import uuid

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from tests.conftest import register_and_verify
from tests.route_walk import iter_routes
from tests.security_policy import (ANY, HIDDEN, LAST, OK, OK404, OK_UPSTREAM, PARAM_OVERRIDES, POLICIES, POLICY,
                                   ROLES, SKIP)
from tests.test_day2_rules import H, ONBOARDING, _pdf_bytes

# внутри маршрута — сначала те, кому нельзя, потом владельцы (их запросы могут менять состояние объекта)
ROLE_ORDER = ("anon", "employer_other", "admin", "fsp_analyst", "expert", "jury_other_employer",
              "jury_other_candidate", "jury_fsp", "jury_expert", "candidate", "employer", "jury_candidate",
              "jury_employer")
assert set(ROLE_ORDER) == set(ROLES)

PROBE = {"title": "Короткая задача", "answer_mode": "any", "time_limit_min": 30,
         "task_text": "Опишите, как бы вы спроектировали идемпотентный платёжный API на FastAPI и PostgreSQL.",
         "salary_from": 200_000, "salary_to": 250_000}
INVITE = {"position_title": "Backend-разработчик", "contact_method": "Почта HR и звонок 20 минут",
          "offer_description": "Команда платежей: FastAPI, PostgreSQL, Redis. Удалённо, гибкий график работы.",
          "salary_from": 220_000, "salary_to": 260_000}
VACANCY = {"title": "Backend-разработчик (матрица прав)", "description": "Вакансия для проверки прав доступа: "
           "сервис платежей, FastAPI и PostgreSQL, удалённая работа.", "stack": ["python"],
           "salary_from": 200_000, "salary_to": 260_000, "work_format": "remote", "publish": True}
NEED_TEXT = ("Нужен backend-разработчик уровня middle: Python, FastAPI, PostgreSQL. Удалённо, вилка 200–250 тыс. ₽ "
             "на руки, опыт от 3 лет.")


def cup_body(category_id: str) -> dict:
    return {"title": "Кубок матрицы прав", "description": "Соревнование в категории для проверки прав доступа к "
            "кубкам работодателя.", "category_id": category_id, "mode": "auto", "n_tasks": 3,
            "time_limit_min": 15, "duration_days": 3, "salary_from": 200_000, "salary_to": 250_000,
            "position_title": "Backend-разработчик", "contact_method": "Почта HR",
            "offer_description": "Приглашение лучшим участникам кубка: команда платежей, удалённо, гибкий график."}


@dataclass
class Side:
    """Объекты одной стороны мира (настоящие пользователи или песочница A)."""
    cand: str
    emp: str
    ids: dict[str, object] = field(default_factory=dict)


def _category_for(client, token: str) -> str:
    return client.get("/api/me/card", headers=H(token)).json()["category"]["id"]


def _session_of(email: str) -> str:
    from app.modules.assessment.models import TestSession
    from app.modules.auth.models import User

    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == email))
        sid = db.scalar(select(TestSession.id).where(TestSession.user_id == uid)
                        .order_by(TestSession.created_at.desc()))
    assert sid, email
    return str(sid)


def build_side(client, cand: str, emp: str) -> Side:
    """Одни и те же объекты на обеих сторонах: потребность, зонд, приглашение, кубок с участием, вакансия с откликом,
    резюме, сессия теста, компания."""
    s = Side(cand, emp)
    me_c = client.get("/api/me", headers=H(cand)).json()
    me_e = client.get("/api/me", headers=H(emp)).json()
    card = client.get("/api/me/card", headers=H(cand)).json()
    s.ids["ref"] = card["ref"]
    s.ids["company_id"] = me_e["employer"]["company"]["id"]
    s.ids["session_id"] = _session_of(me_c["email"])
    r = client.post("/api/employer/needs", json={"text": NEED_TEXT}, headers=H(emp))
    assert r.status_code == 201, r.text
    s.ids["need_id"], s.ids["version"] = r.json()["id"], 1
    r = client.post("/api/employer/probes", json={**PROBE, "candidate_refs": [card["ref"]]}, headers=H(emp))
    assert r.status_code == 201 and r.json()["created"], r.text
    s.ids["probe_id"] = r.json()["created"][0]["id"]
    r = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": card["ref"]}, headers=H(emp))
    if r.status_code == 409:  # кандидат песочницы уже приглашён по итогам демо-кубка (одно за 30 дней) — берём его
        inv = next(i for i in client.get("/api/employer/invitations", headers=H(emp)).json()
                   if i.get("candidate_ref") == card["ref"])
    else:
        assert r.status_code == 201, r.text
        inv = r.json()
    s.ids["inv_id"] = s.ids["tid"] = inv["id"]
    r = client.post("/api/employer/cups", json=cup_body(card["category"]["id"]), headers=H(emp))
    assert r.status_code == 201, r.text
    s.ids["cup_id"] = r.json()["id"]
    r = client.post(f"/api/candidate/cups/{s.ids['cup_id']}/join", headers=H(cand))
    assert r.status_code == 200, r.text
    r = client.get(f"/api/employer/cups/{s.ids['cup_id']}", headers=H(emp)).json()
    assert r["leaderboard"], r
    s.ids["entry_id"] = r["leaderboard"][0]["entry_id"]
    r = client.post("/api/employer/vacancies", json=VACANCY, headers=H(emp))
    assert r.status_code == 201, r.text
    s.ids["vid"] = r.json()["id"]
    r = client.post(f"/api/vacancies/{s.ids['vid']}/apply", json={"consent_contacts": True}, headers=H(cand))
    assert r.status_code == 201, r.text
    s.ids["app_id"] = r.json()["id"]
    pdf = _pdf_bytes(["Иван Петров", "Backend-разработчик", "Python, PostgreSQL, FastAPI", "Опыт 3 года"])
    r = client.post("/api/me/resume", files={"file": ("resume.pdf", io.BytesIO(pdf), "application/pdf")},
                    headers=H(cand))
    assert r.status_code in (200, 201), r.text
    s.ids["resume_id"] = r.json()["id"]
    return s


def _real_user(email: str, role) -> str:
    """Учётка служебной роли (не демо) и её токен — регистрация таких ролей через API закрыта."""
    from app.core.security import hash_password
    from app.modules.auth.models import User
    from app.modules.auth.service import issue_token

    with SessionLocal() as db:
        u = User(email=email, password_hash=hash_password("Matrix-pass-123"), role=role, is_email_verified=True)
        db.add(u)
        db.commit()
        db.refresh(u)
        return issue_token(u).access_token


def _jury(client, persona: str, scenario: str) -> dict:
    r = client.post("/api/jury/login", json={"persona": persona, "scenario": scenario})
    assert r.status_code == 200, r.text
    return r.json()


def build_world(client) -> dict:
    from app.core.enums import UserRole
    from app.modules.auth.models import User
    from app.modules.jury.seed import run_demo_test
    from app.modules.profiles.facts import refresh_rating

    tokens: dict[str, str | None] = {"anon": None}
    # настоящие пользователи
    tokens["candidate"] = register_and_verify(client, "matrix-c1@example.org")
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(tokens["candidate"])).status_code == 200
    with SessionLocal() as db:  # категория — настоящим тестом банка за «демо-респондента», как у персон жюри
        uid = db.scalar(select(User.id).where(User.email == "matrix-c1@example.org"))
        for attempt in range(6):
            res = run_demo_test(db, uid, "middle", 0.9, 9100 + attempt)
            if res.get("category_id"):
                break
        refresh_rating(db, uid)
        db.commit()
    assert client.get("/api/me/card", headers=H(tokens["candidate"])).json()["category"], "у C1 нет категории"
    tokens["employer"] = register_and_verify(client, "matrix-e1@example.org", role="employer", company_name="Матрица 1")
    tokens["employer_other"] = register_and_verify(client, "matrix-e2@example.org", role="employer",
                                                   company_name="Матрица 2")
    tokens["admin"] = _real_user("matrix-admin@example.org", UserRole.admin)
    tokens["fsp_analyst"] = _real_user("matrix-fsp@example.org", UserRole.fsp_analyst)
    tokens["expert"] = _real_user("matrix-expert@example.org", UserRole.expert)
    # песочницы жюри
    a = _jury(client, "employer", "new")
    sid_a = a["scenario"]
    assert sid_a, "песочница A не создана (лимит?)"
    tokens["jury_employer"] = a["access_token"]
    tokens["jury_candidate"] = _jury(client, "candidate", sid_a)["access_token"]
    tokens["jury_expert"] = _jury(client, "expert", sid_a)["access_token"]
    tokens["jury_fsp"] = _jury(client, "fsp", sid_a)["access_token"]
    b = _jury(client, "employer", "new")
    sid_b = b["scenario"]
    assert sid_b and sid_b != sid_a
    tokens["jury_other_employer"] = b["access_token"]
    tokens["jury_other_candidate"] = _jury(client, "candidate", sid_b)["access_token"]
    real = build_side(client, tokens["candidate"], tokens["employer"])
    sandbox = build_side(client, tokens["jury_candidate"], tokens["jury_employer"])
    r = client.post("/api/jury/live/room", headers=H(tokens["jury_employer"]))
    assert r.status_code == 200, r.text
    real.ids["live_code"] = sandbox.ids["live_code"] = r.json()["code"]
    return {"tokens": tokens, "real": real, "sandbox": sandbox, "sid_a": sid_a, "sid_b": sid_b}


# ---------------------------------------------------------------- параметры пути и тела

def params_for(key: tuple[str, str], side: Side) -> dict[str, object]:
    method, path = key
    p: dict[str, object] = {
        **side.ids,
        "path": "apidocs/favicon-32x32.png", "fsp_id": "FSP-770012", "token": "x" * 24, "stub_key": "nope",
        "account_id": 1, "applicant_id": 1, "job_id": 1, "join_id": 1, "vacancy_id": 1, "section": "demand",
        "format": "json", "attack_id": "nope", "pid": "x" * 16, "kind": "processing",
        # ветки, ещё не влитые: объектов этих типов в мире нет — при слиянии добавьте их в build_side
        "aid": str(uuid.uuid4()), "atid": str(uuid.uuid4()), "delivery_id": str(uuid.uuid4()),
    }
    p["code"] = side.ids.get("live_code", "nope") if path.startswith("/api/jury/live/") else "potok"
    p.update(PARAM_OVERRIDES.get(key, {}))
    return p


def fill(path: str, values: dict[str, object]) -> str:
    def sub(m: re.Match) -> str:
        name = m.group(1).split(":")[0]
        assert name in values, f"нет значения для {{{name}}} в {path}: добавьте в params_for или PARAM_OVERRIDES"
        return str(values[name])

    return re.sub(r"\{([^}]+)\}", sub, path)


def body_for(key: tuple[str, str], side: Side) -> dict | None:
    """Тела изменяющих запросов — валидные, чтобы проверка владельца (404 чужому) была раньше валидации (422)."""
    ref = side.ids.get("ref", "C-NOPE")
    bodies: dict[tuple[str, str], dict] = {
        ("POST", "/api/employer/probes"): {**PROBE, "candidate_refs": [ref]},
        ("POST", "/api/employer/invitations"): {**INVITE, "candidate_ref": ref},
        ("POST", "/api/employer/assignments"): {"mode": "probe", "candidate_refs": [ref],
                                                "need_id": side.ids.get("need_id")},
        ("POST", "/api/employer/needs"): {"text": NEED_TEXT},
        ("POST", "/api/employer/needs/parse"): {"text": NEED_TEXT},
        ("PATCH", "/api/employer/needs/{need_id}"): {"title": "Потребность (матрица прав)"},
        ("POST", "/api/employer/needs/{need_id}/selections"): {},
        ("POST", "/api/employer/probes/{probe_id}/review"): {"verdict": "ok"},
        ("POST", "/api/employer/invitations/{inv_id}/counter/accept"): {},
        ("POST", "/api/employer/invitations/{inv_id}/counter/decline"): {},
        ("POST", "/api/employer/cups"): cup_body("backend.middle"),
        ("POST", "/api/employer/cups/{cup_id}/entries/{entry_id}/score"): {"score_pct": 50},
        ("POST", "/api/employer/cups/{cup_id}/finish"): {"early": True},
        ("POST", "/api/employer/vacancies"): VACANCY,
        ("PATCH", "/api/employer/vacancies/{vid}"): {"title": "Вакансия (матрица прав)"},
        ("POST", "/api/employer/applications/{app_id}/status"): {"status": "accepted", "note": "Ждём на интервью"},
        ("PUT", "/api/employer/ats/settings"): {"auto_push": False},
        ("PUT", "/api/employer/ats/providers/{code}"): {"enabled": False, "mode": "demo"},
        ("POST", "/api/employer/ats/push"): {"invitation_id": side.ids.get("inv_id")},
        ("POST", "/api/candidate/probes/{probe_id}/answer"): {"mode": "approach", "text": "Идемпотентность через ключ "
                                                              "запроса и уникальный индекс; состояние — в PostgreSQL."},
        ("POST", "/api/candidate/invitations/{inv_id}/decline"): {},
        ("POST", "/api/candidate/probes/{probe_id}/decline"): {},
        ("POST", "/api/candidate/invitations/{inv_id}/complaint"): {"reason": "other", "comment": "Проверка прав"},
        ("POST", "/api/candidate/invitations/{inv_id}/counter"): {"salary_from": 260_000, "salary_to": 300_000},
        ("POST", "/api/candidate/cups/{cup_id}/submit"): {"answers": {}},
        ("POST", "/api/candidate/assignments/{atid}/submit"): {"answers": {}},
        ("POST", "/api/assessment/sessions"): {"claimed_grade": "middle"},
        ("POST", "/api/assessment/sessions/{session_id}/answers"): {"item_id": "x", "answer": "A"},
        ("PUT", "/api/me/onboarding"): ONBOARDING,
        ("PUT", "/api/me/privacy"): {"privacy": {}},
        ("PUT", "/api/me/jury-mode"): {"enabled": True},
        ("POST", "/api/me/fsp/link"): {"fsp_id": "FSP-770012"},
        ("POST", "/api/me/resume/{resume_id}/apply"): {"stack": True},
        ("PATCH", "/api/me/candidate-profile"): {},
        ("PATCH", "/api/me/company"): {},
        ("POST", "/api/vacancies/{vid}/apply"): {"consent_contacts": True},
        ("POST", "/api/messages/{kind}/{tid}"): {"body": "Здравствуйте, уточните, пожалуйста, формат работы."},
        ("POST", "/api/validation/closed-set/evaluate"): {},
        ("POST", "/api/validation/closed-set/export"): {},
        ("POST", "/api/validation/self-check"): {},
        ("POST", "/api/expert/review"): {},
        ("POST", "/api/expert-panel/labels"): {},
        ("POST", "/api/expert-panel/invites"): {"code": "E9"},
        ("POST", "/api/sus"): {"answers": [3] * 10, "context": "other"},
        ("POST", "/api/push/subscribe"): {"endpoint": "https://push.example.org/sub/1",
                                          "keys": {"p256dh": "x", "auth": "y"}},
        ("POST", "/api/push/unsubscribe"): {"endpoint": "https://push.example.org/sub/1"},
        ("POST", "/api/admin/passports/{pid}/revoke"): {"reason": "admin"},
        ("POST", "/api/passport/verify"): {},
        ("POST", "/api/jury/login"): {"persona": "candidate"},
        ("POST", "/api/jury/live/j/{code}/start"): {},
        ("POST", "/api/fsp-id/start"): {},
    }
    return bodies.get(key)


FILES = {("POST", "/api/me/resume"): lambda: {
    "file": ("resume.pdf", io.BytesIO(_pdf_bytes(["Резюме для матрицы прав"])), "application/pdf")}}


# ---------------------------------------------------------------- ожидания

def expectation(policy) -> dict[str, object]:
    name, over = (policy, {}) if isinstance(policy, str) else policy
    assert name in POLICIES, f"неизвестная политика {name!r}"
    unknown = set(over) - set(ROLES)
    assert not unknown, unknown
    return {**POLICIES[name], **over}


def matches(status: int, want) -> bool:
    if want == OK:
        return status < 500 and status not in (401, 403, 404)
    if want == OK404:
        return status < 500 and status not in (401, 403)
    if want == OK_UPSTREAM:
        return (status < 500 or status == 502) and status not in (401, 403, 404)
    if want == HIDDEN:
        return status in (403, 404)
    if want == ANY:
        return status < 500
    return status == want


def hint(route) -> str:
    guess = ("admin" if route.path.startswith("/api/admin/") else "employer" if route.path.startswith("/api/employer/")
             else "candidate" if route.path.startswith(("/api/candidate/", "/api/me/", "/api/assessment/"))
             else "expert" if route.path.startswith("/api/expert")
             else "fsp" if route.path.startswith("/api/fsp-cabinet/") else "auth")
    return f'    ("{route.method}", "{route.path}"): "{guess}",  # {route.name}'


@pytest.fixture
def no_ats_network(monkeypatch):
    """HTTP к ATS (после принятия приглашения с подключёнными заглушками) — без сети: ошибка сразу, не таймаут."""
    import httpx

    from app.integrations.ats import clients

    def refuse(method, url, **kw):
        raise httpx.ConnectError(f"матрица прав: сеть к ATS отключена ({method} {url})")

    monkeypatch.setattr(clients, "_send", refuse)


def test_every_route_has_a_policy(client):
    routes = iter_routes(client.app)
    assert len(routes) > 150, "обход маршрутов нашёл подозрительно мало — проверьте tests/route_walk.py"
    missing = [r for r in routes if r.key not in POLICY]
    assert not missing, ("Маршруты без политики доступа — добавьте строки в tests/security_policy.py POLICY "
                         "(и тело/параметры, если нужно):\n" + "\n".join(hint(r) for r in missing))
    stale = sorted(k for k in POLICY if k not in {r.key for r in routes})
    print(f"\nполитик без маршрута в этой ветке (ждут слияния): {len(stale)}")


def test_access_matrix(client, no_ats_network):
    routes = iter_routes(client.app)
    assert not [r for r in routes if r.key not in POLICY], "см. test_every_route_has_a_policy"
    world = build_world(client)
    tokens = world["tokens"]
    last = {k: i for i, k in enumerate(LAST)}
    ordered = sorted(routes, key=lambda r: (r.key in last, last.get(r.key, 0), r.path, r.method))
    failures: list[str] = []
    checked = 0
    for route in ordered:
        want_by_role = expectation(POLICY[route.key])
        for role in ROLE_ORDER:
            want = want_by_role[role]
            if want == SKIP:
                continue
            side = world["sandbox"] if role.startswith("jury_") else world["real"]
            url = fill(route.path, params_for(route.key, side))
            kw: dict = {"headers": H(tokens[role]) if tokens[role] else {}}
            if route.key in FILES:
                kw["files"] = FILES[route.key]()
            else:
                body = body_for(route.key, side)
                if body is not None:
                    kw["json"] = body
            resp = client.request(route.method, url, **kw)
            checked += 1
            if not matches(resp.status_code, want):
                failures.append(f"{route.method} {route.path} [{role}] ожидалось {want}, получено {resp.status_code}: "
                                f"{resp.text[:160]!r}")
    print(f"\nпроверено запросов: {checked} ({len(routes)} маршрутов × {len(ROLES)} ролей)")
    assert not failures, f"{len(failures)} расхождений с политикой доступа:\n" + "\n".join(failures)
