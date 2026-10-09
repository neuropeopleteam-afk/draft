"""«Мои данные» кандидата (152-ФЗ): выгрузка без чужих данных, удаление учётной записи (что стирается и что обезличивается),
права, отзыв согласий и доступа к контактам, обезличенная отметка интереса «N работодателей, M подборок, K зондов»."""
from datetime import timedelta
import json
import uuid

import pytest
from sqlalchemy import func, select, text

from app.core.db import SessionLocal, as_aware, utcnow
from tests.conftest import register_and_verify
from tests.test_day2_rules import H, INVITE, candidate_with_category, employer, make_demo, my_ref

NEED = ("Ищем бэкенд-разработчика middle: обязательно Python и PostgreSQL, желательно Kafka. "
        "Удалённо, 200–280 тыс.")
PASSWORD = "Passw0rd!"


def _invite(client, tc, te, **kw) -> dict:
    r = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": my_ref(client, tc), **kw}, headers=H(te))
    assert r.status_code == 201, r.text
    return r.json()


def _uid(email: str) -> uuid.UUID:
    from app.modules.auth.models import User

    with SessionLocal() as db:
        return db.scalar(select(User.id).where(User.email == email))


def _events(uid) -> list:
    from app.modules.mydata.models import InterestEvent

    with SessionLocal() as db:
        return list(db.scalars(select(InterestEvent).where(InterestEvent.candidate_user_id == uid)).all())


def _delete(client, t, **kw):
    return client.post("/api/me/data/delete", json={"confirm": "УДАЛИТЬ", "password": PASSWORD, **kw}, headers=H(t))


@pytest.fixture
def world(client):
    """Два кандидата, работодатель, приглашение каждому, зонд первому, ответ и переписка у первого."""
    tc = candidate_with_category(client, "cand@example.com")
    tc2 = candidate_with_category(client, "other@example.com")
    client.patch("/api/me/candidate-profile", json={"full_name": "Пётр Другой", "phone": "+7 900 555-66-77"}, headers=H(tc2))
    te = employer(client, "hr@corp.ru", "ООО Ромашка")
    inv = _invite(client, tc, te)
    inv2 = _invite(client, tc2, te)
    return {"tc": tc, "tc2": tc2, "te": te, "inv": inv, "inv2": inv2, "ref": my_ref(client, tc), "ref2": my_ref(client, tc2)}


# ------------------------------------------------------------------ права

def test_my_data_endpoints_only_for_candidate(client, world):
    paths = [("GET", "/api/me/data"), ("GET", "/api/me/data/export"), ("GET", "/api/me/data/delete/preview"),
             ("GET", "/api/me/interest"), ("POST", "/api/me/data/contacts/revoke"),
             ("POST", "/api/me/data/delete")]
    for method, path in paths:
        assert client.request(method, path, json={} if method == "POST" else None).status_code == 401, path
        assert client.request(method, path, headers=H(world["te"]), json={} if method == "POST" else None).status_code == 403, path
    # работодатель не удалён: запрос отклонён до всякой работы
    assert client.get("/api/employer/needs", headers=H(world["te"])).status_code == 200


# ------------------------------------------------------------------ обзор

def test_overview_lists_what_is_stored(client, world):
    d = client.get("/api/me/data", headers=H(world["tc"])).json()
    keys = {s["key"]: s for s in d["stored"]}
    assert keys["profile"]["count"] == 1 and keys["tests"]["count"] >= 1 and keys["invitations"]["count"] == 1
    assert keys["consents"]["count"] >= 2 and keys["survey"]["count"] >= 1
    kinds = {c["kind"]: c for c in d["consents"]}
    assert kinds["publication"]["active"] and kinds["processing"]["revoke"] == "delete_account"
    assert d["delete"]["phrase"] == "УДАЛИТЬ" and d["delete"]["needs_password"] and not d["delete"]["needs_code"]
    assert d["contacts_open_to"] == [] and d["not_in_our_power"] and "14" in d["backups"]
    assert d["operator"]["email"]


# ------------------------------------------------------------------ выгрузка

def test_export_contains_own_data_and_nothing_foreign(client, world):
    tc, te = world["tc"], world["te"]
    # принять приглашение: контакты открыты работодателю, он пишет сообщение
    inv = world["inv"]
    assert client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc)).status_code == 200
    r = client.get("/api/me/data/export", headers=H(tc))
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment;") and r.headers["content-disposition"].endswith('.json"')
    assert r.headers["content-type"].startswith("application/json")
    raw = r.text
    data = json.loads(raw)
    assert data["format"].startswith("vstrechny.my-data/")
    assert data["account"]["email"] == "cand@example.com" and data["account"]["role"] == "candidate"
    p = data["profile"]
    assert p["full_name"] == "Иван Петров" and p["phone"] == "+7 900 111-22-33" and p["salary_min_hidden"] == 250000
    assert p["public_ref"] == world["ref"]
    assert data["tests"]["sessions"] and data["tests"]["sessions"][0]["answers"]
    assert data["survey"] and data["survey"][0]["stack"]
    assert {c["kind"] for c in data["consents"]} >= {"processing", "publication"}
    assert len(data["invitations"]) == 1 and data["invitations"][0]["company"]["name"] == "ООО Ромашка"
    assert data["interest"]["period_days"] == 7
    # чужого нет: ни другого кандидата, ни его ref, ни почты работодателя
    for foreign in ("other@example.com", "Пётр Другой", "+7 900 555-66-77", world["ref2"], "hr@corp.ru"):
        assert foreign not in raw, foreign
    # секретов и банка заданий нет
    for secret in ("password_hash", "secret_enc", "answer_key", "code_hash", "$argon2", "grading"):
        assert secret not in raw, secret
    # из ответов теста — только позиция/ответ/итог; нет вариантов и ключей заданий
    a0 = data["tests"]["sessions"][0]["answers"][0]
    assert set(a0) == {"position", "answer", "is_correct", "score", "time_spent_ms", "answered_at"} and a0["position"]


def test_export_contacts_open_only_after_accept(client, world):
    tc = world["tc"]
    d0 = json.loads(client.get("/api/me/data/export", headers=H(tc)).text)
    assert d0["contacts_open_to"] == [] and d0["invitations"][0]["employer_contact_method"] is None
    r = client.post(f"/api/candidate/invitations/{world['inv']['id']}/accept", headers=H(tc))
    assert r.status_code == 200, r.text
    d1 = json.loads(client.get("/api/me/data/export", headers=H(tc)).text)
    assert d1["contacts_open_to"][0]["company"]["name"] == "ООО Ромашка"
    assert d1["invitations"][0]["employer_contact_method"] == INVITE["contact_method"]
    # у второго кандидата контакты никому не открыты, и его выгрузка не знает про первого
    d2 = json.loads(client.get("/api/me/data/export", headers=H(world["tc2"])).text)
    assert d2["contacts_open_to"] == [] and world["ref"] not in json.dumps(d2, ensure_ascii=False)


def test_export_covers_every_owned_table(client, world):
    """Выгрузка не отстаёт от схемы: каждая таблица с данными учётной записи либо выгружается разделом, либо в ``other``."""
    from app.modules.mydata import erase, export

    uid = _uid("cand@example.com")
    owned = set(erase.owned_tables(uid))
    with SessionLocal() as db:
        from app.modules.auth.models import User

        data = export.build(db, db.get(User, uid))
    other = set(data["other"])
    assert other.isdisjoint(export.SECTION_TABLES | {"assignment_attempts"})
    assert owned - export.SECTION_TABLES - {"assignment_attempts"} == other


# ------------------------------------------------------------------ удаление: подтверждение

def test_delete_requires_phrase_password_and_second_factor(client, world):
    tc = world["tc"]
    r = client.post("/api/me/data/delete", json={"confirm": "да", "password": PASSWORD}, headers=H(tc))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "confirm_phrase"
    r = _delete(client, tc, password="неверный")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "wrong_password"
    r = client.post("/api/me/data/delete", json={"confirm": "УДАЛИТЬ"}, headers=H(tc))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "wrong_password"
    # ничего не удалено
    assert client.get("/api/me", headers=H(tc)).status_code == 200
    assert json.loads(client.get("/api/me/data/export", headers=H(tc)).text)["profile"]["full_name"] == "Иван Петров"


def test_delete_with_second_factor_needs_code(client, world):
    from app.core import totp
    from app.modules.auth.models import User, UserTwoFactor

    tc = world["tc"]
    secret = client.post("/api/auth/2fa/setup", headers=H(tc)).json()["secret"]
    r = client.post("/api/auth/2fa/confirm", json={"code": totp.totp(secret)}, headers=H(tc))
    assert r.status_code == 200, r.text
    assert client.get("/api/me/data", headers=H(tc)).json()["delete"]["needs_code"]
    r = _delete(client, tc)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "second_factor_required"
    r = _delete(client, tc, code="000000")
    assert r.status_code == 400
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(User).where(User.email == "cand@example.com")) == 1
    r = _delete(client, tc, code=totp.totp(secret, utcnow().timestamp() + 30))  # следующий шаг: прежний уже использован
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(UserTwoFactor)) == 0  # второй фактор стёрт вместе с учёткой


def test_delete_attempts_are_rate_limited(client, world):
    tc = world["tc"]
    for _ in range(8):
        assert _delete(client, tc, password="неверный").status_code == 403
    r = _delete(client, tc)  # верный пароль после перебора — тоже отказ: окно исчерпано
    assert r.status_code == 429 and r.json()["detail"]["code"] == "too_many_attempts"


def test_delete_preview_counts(client, world):
    d = client.get("/api/me/data/delete/preview", headers=H(world["tc"])).json()
    assert d["deleted"]["Попытки теста"] >= 1 and d["deleted"]["Согласия"] >= 2
    assert d["anonymized"]["Приглашения работодателей"] == 1
    assert d["confirm"]["needs_password"] and d["not_in_our_power"]
    # предпросмотр ничего не удаляет
    assert client.get("/api/me", headers=H(world["tc"])).status_code == 200


# ------------------------------------------------------------------ удаление: результат

def _row_counts(uid) -> dict[str, int]:
    """Сколько строк в каждой таблице ссылается на учётку (по любому внешнему ключу на users/candidate_profiles)."""
    from app.models import metadata

    out = {}
    with SessionLocal() as db:
        for t in metadata.sorted_tables:
            for fk in t.foreign_keys:
                if fk.column.table.name in ("users", "candidate_profiles") and fk.column.name in ("id", "user_id"):
                    n = db.scalar(select(func.count()).select_from(t).where(t.c[fk.parent.name] == uid)) or 0
                    if n:
                        out[f"{t.name}.{fk.parent.name}"] = n
    return out


def test_delete_erases_personal_data_and_anonymizes_employer_records(client, world):
    from app.core.enums import InvitationStatus
    from app.modules.auth.models import User
    from app.modules.invitations.models import Invitation, Probe
    from app.modules.profiles.models import CandidateProfile

    tc, te, inv = world["tc"], world["te"], world["inv"]
    uid = _uid("cand@example.com")
    ref = world["ref"]
    # отказ с причиной — тексты кандидата, которые должны исчезнуть из записи работодателя
    r = client.post(f"/api/candidate/invitations/{inv['id']}/decline", json={"reason": "Ищу удалённую работу в Казани"}, headers=H(tc))
    assert r.status_code == 200, r.text
    # зонд и ответ на него
    r = client.post("/api/employer/probes", json={"candidate_refs": [ref], "title": "Короткая задача", "task_text": "Опишите подход к кэшированию.",
                                                  "salary_from": 200000, "salary_to": 250000, "time_limit_min": 15}, headers=H(te))
    assert r.status_code == 201, r.text
    pid = r.json()["created"][0]["id"]
    r = client.post(f"/api/candidate/probes/{pid}/answer", json={"mode": "approach", "text": "Кэширую в Redis, Иван Петров, +7 900 111-22-33"}, headers=H(tc))
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Probe)) == 1
    before = _row_counts(uid)
    assert before.get("test_sessions.user_id") and before.get("consents.user_id") and before.get("invitations.candidate_user_id")

    r = _delete(client, tc)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] and out["deleted"]["Попытки теста"] >= 1 and out["anonymized"]["Приглашения работодателей"] == 1
    assert out["not_in_our_power"] and out["backups"]

    # 1. вход невозможен: прежний токен, пароль
    assert client.get("/api/me", headers=H(tc)).status_code == 401
    assert client.post("/api/auth/login", json={"email": "cand@example.com", "password": PASSWORD}).status_code == 401
    # 2. остатков нет: из всех таблиц с внешним ключом на учётку остались только обезличенные записи работодателя
    left = _row_counts(uid)
    assert set(left) <= {"users.id", "candidate_profiles.user_id", "invitations.candidate_user_id", "probes.candidate_user_id",
                         "invitation_complaints.candidate_user_id", "invitation_counters.candidate_user_id",
                         "vacancy_applications.candidate_user_id", "invitation_events.actor_user_id"}, left
    # 3. надгробие: профиль без личных данных, ref сохранён
    with SessionLocal() as db:
        p = db.get(CandidateProfile, uid)
        u = db.get(User, uid)
        assert p.deleted_at is not None and p.public_ref == ref
        assert not any([p.full_name, p.phone, p.telegram, p.city, p.headline, p.about, p.salary_min_hidden,
                        p.current_category_id, p.fsp_id_claimed, p.visible_to_employers, p.privacy, p.roles])
        assert u.email.endswith("@deleted.invalid") and "cand" not in u.email and not u.is_active
        assert u.password_hash == "!deleted" and u.token_version >= 1
        # 4. записи работодателя остались, тексты кандидата стёрты
        i = db.scalars(select(Invitation).where(Invitation.candidate_user_id == uid)).one()
        assert i.status == InvitationStatus.declined and i.decline_reason is None and i.evidence == []
        pr = db.scalars(select(Probe).where(Probe.candidate_user_id == uid)).one()
        assert pr.answer is None and all(not e.get("note") for e in pr.events if e.get("by") == "candidate")
        # ни в одной таблице не осталось ни имени, ни телефона, ни почты, ни текста ответа
        dump = _dump_all(db)
        for pii in ("Иван Петров", "+7 900 111-22-33", "cand@example.com", "Ищу удалённую работу в Казани", "Кэширую в Redis"):
            assert pii not in dump, pii
    # 5. журнал уничтожения — без идентификаторов
    from app.modules.mydata.models import AccountDeletionLog

    with SessionLocal() as db:
        lg = db.scalars(select(AccountDeletionLog)).one()
        s = json.dumps(lg.details, ensure_ascii=False)
        assert lg.role == "candidate" and str(uid) not in s and "cand@" not in s and ref not in s
    # 6. работодатель видит свой список приглашений без ошибок и без нового ПДн
    r = client.get("/api/employer/invitations", headers=H(te))
    assert r.status_code == 200
    assert {x["status"] for x in r.json()} >= {"declined"}
    assert client.get("/api/employer/probes", headers=H(te)).status_code == 200
    # 7. карточка удалённого кандидата работодателю недоступна, в подборках его нет
    assert client.get(f"/api/employer/candidates/{ref}", headers=H(te)).status_code == 404
    need = client.post("/api/employer/needs", json={"text": NEED}, headers=H(te)).json()
    v = client.get(f"/api/employer/needs/{need['id']}/selections/1", headers=H(te)).json()
    assert [x["ref"] for x in v["results"]] == [world["ref2"]]
    # 8. другой кандидат не затронут
    assert client.get("/api/me", headers=H(world["tc2"])).status_code == 200
    assert json.loads(client.get("/api/me/data/export", headers=H(world["tc2"])).text)["profile"]["full_name"] == "Пётр Другой"


def _dump_all(db) -> str:
    """Все значения всех таблиц одной строкой — для проверки «ПДн нигде не осталось»."""
    from app.models import metadata

    parts = []
    for t in metadata.sorted_tables:
        if t.name in ("grade_passports",):
            continue
        for row in db.execute(select(t)).all():
            parts.append(json.dumps([str(v) for v in row], ensure_ascii=False))
    return "\n".join(parts)


def test_email_is_free_after_deletion_and_old_token_is_dead(client, world):
    assert _delete(client, world["tc"]).status_code == 200
    t2 = register_and_verify(client, email="cand@example.com")  # та же почта — новая учётная запись
    assert client.get("/api/me", headers=H(t2)).status_code == 200
    assert client.get("/api/me/data", headers=H(t2)).json()["stored"][1]["count"] == 1
    # новая запись — чистая: нет ни теста, ни приглашений прежней
    d = json.loads(client.get("/api/me/data/export", headers=H(t2)).text)
    assert d["tests"]["sessions"] == [] and d["invitations"] == [] and d["profile"]["public_ref"] != world["ref"]


def test_delete_removes_messages_and_applications_text(client, world):
    from app.modules.contact.models import ContactMessage

    tc, te, inv = world["tc"], world["te"], world["inv"]
    assert client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc)).status_code == 200
    r = client.post(f"/api/messages/invitation/{inv['id']}", json={"body": "Здравствуйте, Иван, когда удобно созвониться?"}, headers=H(te))
    assert r.status_code in (200, 201), r.text
    r = client.post(f"/api/messages/invitation/{inv['id']}", json={"body": "Завтра после обеда"}, headers=H(tc))
    assert r.status_code in (200, 201), r.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ContactMessage)) == 2
    assert _delete(client, tc).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ContactMessage)) == 0
    # работодатель видит приглашение «принято», без контактов и без нового ПДн
    lst = client.get("/api/employer/invitations", headers=H(te)).json()
    assert any(x["status"] == "accepted" for x in lst)


def test_delete_revokes_grade_passport(client, world):
    from app.passport.models import GradePassport

    tc, ref = world["tc"], world["ref"]
    uid = _uid("cand@example.com")
    assert client.get("/api/me/passport", headers=H(tc)).status_code == 200
    assert client.get("/api/me/passport", headers=H(world["tc2"])).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(GradePassport).where(GradePassport.user_id == uid)) == 1
    assert _delete(client, tc).status_code == 200
    with SessionLocal() as db:
        mine = db.scalars(select(GradePassport).where(GradePassport.public_ref == ref)).all()
        assert len(mine) == 1 and mine[0].user_id is None and mine[0].revoked_at is not None
        assert mine[0].revoke_reason == "account_deleted"
        assert db.scalar(select(func.count()).select_from(GradePassport).where(GradePassport.user_id == uid)) == 0
        # паспорт другого кандидата не затронут
        other = db.scalars(select(GradePassport).where(GradePassport.public_ref == world["ref2"])).one()
        assert other.user_id is not None and other.revoked_at is None


def test_demo_account_confirms_by_email_and_shared_demo_is_protected(client):
    from app.modules.jury.seed import create_jury

    with SessionLocal() as db:
        create_jury(db, "mydata0001")
    r = client.post("/api/jury/login", json={"persona": "candidate_new", "scenario": "mydata0001"})
    assert r.status_code == 200, r.text
    t = r.json()["access_token"]
    d = client.get("/api/me/data", headers=H(t)).json()
    assert d["delete"]["demo"] and d["delete"]["needs_email"] and not d["delete"]["needs_password"]
    bad = client.post("/api/me/data/delete", json={"confirm": "УДАЛИТЬ", "email": "x@example.com"}, headers=H(t))
    assert bad.status_code == 403 and bad.json()["detail"]["code"] == "wrong_email"
    ok = client.post("/api/me/data/delete", json={"confirm": "УДАЛИТЬ", "email": "candidate-new+mydata0001@jury.example.com"}, headers=H(t))
    assert ok.status_code == 200, ok.text
    assert client.get("/api/me", headers=H(t)).status_code == 401
    # песочница пересоздаётся при следующем входе (учётка удалена — «полная» ли песочница — решает ensure)
    r = client.post("/api/jury/login", json={"persona": "candidate_new", "scenario": "mydata0001"})
    assert r.status_code == 200, r.text
    assert client.get("/api/me", headers=H(r.json()["access_token"])).status_code == 200


# ------------------------------------------------------------------ согласия и контакты

def test_revoke_consents_and_contacts(client, world):
    tc = world["tc"]
    assert client.delete("/api/me/consents/publication", headers=H(tc)).status_code == 200
    d = client.get("/api/me/data", headers=H(tc)).json()
    assert {c["kind"]: c["active"] for c in d["consents"]}["publication"] is False
    assert client.get(f"/api/employer/candidates/{world['ref']}", headers=H(world["te"])).status_code == 404
    assert client.delete("/api/me/consents/processing", headers=H(tc)).status_code == 409  # = удаление учётной записи
    # массовый отзыв доступа к контактам
    assert client.post(f"/api/candidate/invitations/{world['inv']['id']}/accept", headers=H(tc)).status_code == 200
    assert len(client.get("/api/me/data", headers=H(tc)).json()["contacts_open_to"]) == 1
    r = client.post("/api/me/data/contacts/revoke", headers=H(tc))
    assert r.status_code == 200 and r.json()["revoked"] == 1 and r.json()["contacts_open_to"] == []
    assert client.post("/api/me/data/contacts/revoke", headers=H(tc)).json()["revoked"] == 0


# ------------------------------------------------------------------ интерес

def test_interest_counts_distinct_employers_and_dedups(client, world):
    from app.modules.mydata import interest

    te, ref = world["te"], world["ref"]
    uid = _uid("cand@example.com")
    s0 = client.get("/api/me/interest", headers=H(world["tc"])).json()
    assert (s0["employers_viewed"], s0["selections"], s0["probes"]) == (0, 0, 0) and s0["has_category"]
    assert client.get(f"/api/employer/candidates/{ref}", headers=H(te)).status_code == 200
    assert client.get(f"/api/employer/candidates/{ref}", headers=H(te)).status_code == 200  # повтор — не новое событие
    assert client.get(f"/api/employer/candidates/{ref}/profile.pdf", headers=H(te)).status_code in (200, 501, 503)
    assert len(_events(uid)) == 1
    te2 = employer(client, "hr2@corp2.ru", "ООО Вторая")
    assert client.get(f"/api/employer/candidates/{ref}", headers=H(te2)).status_code == 200
    s = client.get("/api/me/interest", headers=H(world["tc"])).json()
    assert s["employers_viewed"] == 2 and s["selections"] == 0
    # по прошествии 6 часов повторное открытие той же компанией — снова событие, но работодатель всё равно один
    with SessionLocal() as db:
        for e in _events(uid):
            e.created_at = utcnow() - timedelta(hours=7)
            db.merge(e)
        db.commit()
    assert client.get(f"/api/employer/candidates/{ref}", headers=H(te)).status_code == 200
    assert client.get("/api/me/interest", headers=H(world["tc"])).json()["employers_viewed"] == 2
    assert len(_events(uid)) == 3
    # чужой кандидат не получил чужих событий
    assert client.get("/api/me/interest", headers=H(world["tc2"])).json()["employers_viewed"] == 0
    assert interest.WINDOW_DAYS == 7


def test_interest_window_is_seven_days_with_previous_week(client, world):
    from app.modules.mydata.models import InterestEvent

    uid = _uid("cand@example.com")
    now = utcnow()
    with SessionLocal() as db:
        for days, kind in ((1, "card_view"), (3, "card_view"), (6, "card_view"), (9, "card_view"), (12, "card_view"), (20, "card_view")):
            db.add(InterestEvent(candidate_user_id=uid, kind=kind, company_key=uuid.uuid4(), created_at=now - timedelta(days=days)))
        db.commit()
    s = client.get("/api/me/interest", headers=H(world["tc"])).json()
    assert s["employers_viewed"] == 3 and s["previous"]["employers_viewed"] == 2  # 20 дней назад — ни там, ни там
    assert len(s["by_day"]) == 7 and sum(d["views"] for d in s["by_day"]) == 3


def test_interest_selection_hook_counts_needs_not_refinements(client, world):
    te = world["te"]
    uid = _uid("cand@example.com")
    need = client.post("/api/employer/needs", json={"text": NEED}, headers=H(te)).json()
    # уточнение фильтров той же потребности — та же подборка
    assert client.post(f"/api/employer/needs/{need['id']}/selections", json={"parent_version": 1, "filters": {}}, headers=H(te)).status_code == 201
    need2 = client.post("/api/employer/needs", json={"text": NEED + " Нужен второй специалист."}, headers=H(te)).json()
    assert need2["id"] != need["id"]
    s = client.get("/api/me/interest", headers=H(world["tc"])).json()
    assert s["selections"] == 2 and s["best_rank"] in (1, 2)
    kinds = [e.kind for e in _events(uid)]
    assert kinds.count("selection") == 2 and kinds.count("card_view") == 0  # просмотр списка — не просмотр карточки


def test_interest_counts_probes_and_never_returns_company_names(client, world):
    te, ref = world["te"], world["ref"]
    r = client.post("/api/employer/probes", json={"candidate_refs": [ref], "title": "Короткая задача", "task_text": "Опишите подход к кэшированию запросов.",
                                                  "salary_from": 200000, "salary_to": 250000, "time_limit_min": 15}, headers=H(te))
    assert r.status_code == 201, r.text
    client.get(f"/api/employer/candidates/{ref}", headers=H(te))
    client.post("/api/employer/needs", json={"text": NEED}, headers=H(te))
    s = client.get("/api/me/interest", headers=H(world["tc"])).json()
    assert (s["employers_viewed"], s["selections"], s["probes"]) == (1, 1, 1)
    blob = json.dumps(s, ensure_ascii=False)
    for name in ("Ромашка", "corp.ru", "ООО"):
        assert name not in blob
    # экспорт: интерес — агрегаты, названий нет
    exp = json.loads(client.get("/api/me/data/export", headers=H(world["tc"])).text)["interest"]
    assert "Ромашка" not in json.dumps(exp, ensure_ascii=False)


def test_interest_hook_failure_does_not_break_card(client, world, monkeypatch):
    from app.modules.mydata import interest

    def boom(*a, **k):
        raise RuntimeError("сбой")

    monkeypatch.setattr(interest, "InterestEvent", boom)
    assert client.get(f"/api/employer/candidates/{world['ref']}", headers=H(world["te"])).status_code == 200


def test_interest_purge_old(client, world):
    from app.modules.mydata import interest
    from app.modules.mydata.models import InterestEvent

    uid = _uid("cand@example.com")
    with SessionLocal() as db:
        db.add_all([InterestEvent(candidate_user_id=uid, kind="card_view", company_key=uuid.uuid4(), created_at=utcnow() - timedelta(days=d))
                    for d in (1, 91, 200)])
        db.commit()
        assert interest.purge_old(db) == 2
        db.commit()
    assert len(_events(uid)) == 1


def test_interest_purge_runs_when_selection_is_built(client, world, monkeypatch):
    """Старые события чистятся при построении подборки (без планировщика), не чаще раза в сутки."""
    from app.modules.mydata import interest
    from app.modules.mydata.models import InterestEvent

    uid = _uid("cand@example.com")
    with SessionLocal() as db:
        db.add(InterestEvent(candidate_user_id=uid, kind="card_view", company_key=uuid.uuid4(), created_at=utcnow() - timedelta(days=120)))
        db.commit()
    monkeypatch.setattr(interest, "_last_purge", None)
    client.post("/api/employer/needs", json={"text": NEED}, headers=H(world["te"]))
    assert all(as_aware(e.created_at) > utcnow() - timedelta(days=90) for e in _events(uid))
    assert interest._last_purge is not None


# ------------------------------------------------------------------ демо жюри

def test_jury_personas_have_nonzero_interest(client):
    from app.modules.jury.seed import create_jury

    with SessionLocal() as db:
        create_jury(db, "mydata0002")
    got = {}
    for persona in ("candidate", "candidate_nofsp", "candidate_junior", "candidate_new"):
        t = client.post("/api/jury/login", json={"persona": persona, "scenario": "mydata0002"}).json()["access_token"]
        got[persona] = client.get("/api/me/interest", headers=H(t)).json()
    m = got["candidate"]
    assert m["employers_viewed"] > 0 and m["selections"] > 0 and m["probes"] > 0 and m["best_rank"]
    assert sum(d["views"] for d in m["by_day"]) > 0 and m["previous"]["employers_viewed"] > 0
    assert got["candidate_nofsp"]["employers_viewed"] > 0 and got["candidate_junior"]["selections"] > 0
    # персона без категории — честный ноль
    n = got["candidate_new"]
    assert (n["employers_viewed"], n["selections"], n["probes"]) == (0, 0, 0) and not n["has_category"]


# ------------------------------------------------------------------ миграция и схема

def test_migration_md01_tables_and_column(engine):
    from sqlalchemy import inspect

    insp = inspect(engine)
    assert {"candidate_interest_events", "account_deletion_log"} <= set(insp.get_table_names())
    assert "deleted_at" in {c["name"] for c in insp.get_columns("candidate_profiles")}
    idx = {i["name"] for i in insp.get_indexes("candidate_interest_events")}
    assert "ix_candidate_interest_events_cand_created" in idx


def test_every_new_owned_table_is_classified():
    """Любая таблица с каскадной ссылкой на учётку попадает в удаление автоматически; двусторонние записи — только по
    явному списку KEEP. Эта проверка не даёт молча забыть таблицу, добавленную позже."""
    from app.modules.mydata import erase

    owned = set(erase.owned_tables(uuid.uuid4()))
    assert {"test_sessions", "test_answers", "candidate_facts", "consents", "proctor_events", "fsp_achievements",
            "candidate_interest_events", "survey_stack_tags"} <= owned
    assert not (owned & erase.KEEP) and not (owned & erase.SPECIAL)
    assert erase.KEEP == {"probes", "invitations", "invitation_complaints", "invitation_counters", "vacancy_applications",
                          "invitation_events"}


# ------------------------------------------------------------------ работодатель после удаления кандидата

def test_employer_side_survives_deleted_candidate(client, world):
    """Работодатель после удаления кандидата: приглашение «принято» без контактов, переписка закрыта, отклик снят,
    списки без ошибок; контактов-обезличенной-почты нет нигде."""
    from app.modules.contact.models import ContactMessage
    from app.integrations.vacancies.models import VacancyApplication

    tc, te, inv = world["tc"], world["te"], world["inv"]
    vac = {"title": "Backend-разработчик (удаление)", "description": "Вакансия для проверки удаления кандидата: сервис платежей.",
           "stack": ["python"], "salary_from": 200_000, "salary_to": 260_000, "work_format": "remote", "publish": True}
    v = client.post("/api/employer/vacancies", json=vac, headers=H(te)).json()
    r = client.post(f"/api/vacancies/{v['id']}/apply", json={"consent_contacts": True, "cover_letter": "Я Иван Петров, пишите на cand@example.com"},
                    headers=H(tc))
    assert r.status_code == 201, r.text
    assert client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc)).status_code == 200
    mine = client.get("/api/employer/invitations", headers=H(te)).json()
    assert any(x.get("contacts") for x in mine)  # до удаления контакты открыты

    assert _delete(client, tc).status_code == 200

    lst = client.get("/api/employer/invitations", headers=H(te)).json()
    row = next(x for x in lst if x["id"] == inv["id"])
    assert row["status"] == "accepted" and row["candidate_deleted"] is True and row["contacts"] is None
    assert "deleted.invalid" not in json.dumps(lst, ensure_ascii=False)
    apps = client.get(f"/api/employer/vacancies/{v['id']}/applications", headers=H(te)).json()
    assert apps[0]["status"] == "withdrawn" and apps[0]["cover_letter"] is None
    assert "deleted.invalid" not in json.dumps(apps, ensure_ascii=False)
    # писать некому: переписка закрыта
    r = client.post(f"/api/messages/invitation/{inv['id']}", json={"body": "Добрый день, на связи?"}, headers=H(te))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "thread_closed"
    th = client.get(f"/api/messages/invitation/{inv['id']}", headers=H(te)).json()
    assert th["messages"] == [] and "удалил" in (th.get("reason") or "")
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ContactMessage)) == 0
        a = db.scalars(select(VacancyApplication)).one()
        assert a.cover_letter is None
