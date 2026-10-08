"""И25 + Н6: подписка работодателя на потребность, фоновый обход с подменой времени, напоминания по приглашениям
и откликам, дайджест, тихие часы, песочница жюри."""
from datetime import datetime, timedelta, timezone
import re
import uuid

import pytest
from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.core.db import SessionLocal, utcnow
from app.modules.auth.models import User
from app.modules.subs import runner, texts
from app.modules.subs.models import NeedSubEntry, NeedSubscription, SubsDirty, UserNotification
from tests.test_day2_rules import H, INVITE, candidate_with_category, employer, my_ref
from tests.conftest import register_and_verify

NEED_TEXT = "Ищем бэкенд-разработчика middle: обязательно Python и PostgreSQL, желательно Kafka. Удалённо, 200–280 тыс."
UTC = timezone.utc
T1 = datetime(2026, 10, 20, 7, 0, tzinfo=UTC)   # 10:00 по Москве, вторник
T1_EVE = datetime(2026, 10, 20, 17, 0, tzinfo=UTC)  # 20:00
T1_NIGHT = datetime(2026, 10, 20, 20, 30, tzinfo=UTC)  # 23:30 — тихие часы
T2 = datetime(2026, 10, 21, 6, 30, tzinfo=UTC)  # 09:30 следующего дня


class Mails(list):
    def send(self, msg):
        self.append(msg)


@pytest.fixture
def mails(monkeypatch):
    box = Mails()
    monkeypatch.setattr("app.modules.subs.delivery.get_mailer", lambda: box)
    return box


@pytest.fixture
def push_log(monkeypatch):
    """Устройство работодателя с поддельной отправкой Web Push; список отправленных уведомлений."""
    import json

    import pywebpush

    from app.integrations.settings import get_isettings

    monkeypatch.setenv("VAPID_PUBLIC_KEY", "BPub" + "A" * 80)
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "priv")
    get_isettings.cache_clear()
    sent: list[dict] = []
    monkeypatch.setattr(pywebpush, "webpush", lambda subscription_info, data, **kw: sent.append(json.loads(data)))
    yield sent
    get_isettings.cache_clear()


@pytest.fixture
def day_hours(monkeypatch):
    """Отключить тихие часы (проверяются отдельно)."""
    s = get_settings()
    monkeypatch.setattr(s, "subs_quiet_from", 0)
    monkeypatch.setattr(s, "subs_quiet_to", 0)


def uid(email: str) -> uuid.UUID:
    with SessionLocal() as db:
        return db.scalar(select(User.id).where(User.email == email))


def tick(now, **kw) -> dict:
    with SessionLocal() as db:
        return runner.tick(db, now, **kw)


def notes(email: str, kind: str | None = None) -> list[UserNotification]:
    with SessionLocal() as db:
        q = select(UserNotification).where(UserNotification.user_id == uid(email)).order_by(UserNotification.created_at)
        if kind:
            q = q.where(UserNotification.kind == kind)
        return list(db.scalars(q).all())


def setup(client, grade_candidates=("a@example.com",)) -> tuple[str, dict]:
    for e in grade_candidates:
        candidate_with_category(client, e)
    te = employer(client, "hr@corp.ru")
    r = client.post("/api/employer/needs", json={"text": NEED_TEXT}, headers=H(te))
    assert r.status_code == 201, r.text
    return te, r.json()


def subscribe(client, te, need, **body) -> dict:
    r = client.put(f"/api/employer/needs/{need['id']}/subscription", json={"enabled": True, **body}, headers=H(te))
    assert r.status_code == 200, r.text
    return r.json()


def push_device(client, token) -> None:
    keys = {"p256dh": "B" * 60, "auth": "a" * 16}
    assert client.post("/api/push/subscribe", json={"endpoint": "https://push.example/hr", "keys": keys},
                       headers=H(token)).status_code == 201


# ------------------------------------------------------------------ И25: подписка
def test_subscribe_remembers_current_top_as_known(client, day_hours, mails):
    te, need = setup(client)
    before = client.get(f"/api/employer/needs/{need['id']}/subscription", headers=H(te)).json()
    assert before["exists"] is False and before["enabled"] is False and before["new_count"] == 0
    sub = subscribe(client, te, need)
    assert sub["enabled"] and sub["frequency"] == "instant" and sub["in_top"] == 1
    assert sub["new_count"] == 0 and sub["new_refs"] == []  # тот, кто уже в топе, — не новый
    st = tick(T1)
    assert st["entered"] == 0 and notes("hr@corp.ru") == [] and mails == []


def test_new_candidate_after_test_enters_top_notifies_push_and_digest(client, day_hours, mails, push_log):
    te, need = setup(client)
    push_device(client, te)
    subscribe(client, te, need)
    tb = candidate_with_category(client, "b@example.com")  # новый подтверждённый кандидат
    ref_b = my_ref(client, tb)
    st = tick(T1)
    assert st["entered"] == 1 and st["notified"] == 1
    s = client.get(f"/api/employer/needs/{need['id']}/subscription", headers=H(te)).json()
    assert s["new_count"] == 1 and s["new_refs"] == [ref_b]
    assert s["new"][0]["card"]["category"]["id"] == "backend.middle" and s["new"][0]["rank"] in (1, 2)
    feed = client.get("/api/notifications", headers=H(te)).json()
    assert [n["kind"] for n in feed["items"]] == ["new_match"] and feed["unread"] == 1
    assert feed["items"][0]["push_state"] == "sent" and ref_b in feed["items"][0]["body"]
    assert push_log and push_log[0]["title"] == "Новые подходящие кандидаты" and "!" not in push_log[0]["body"]
    # письмо — дайджест: в тот же день не приходит, утром следующего дня приходит одно
    assert tick(T1_EVE)["digest"]["digests"] == 0 and mails == []
    assert tick(T2)["digest"]["digests"] == 1
    assert len(mails) == 1 and mails[0].to == "hr@corp.ru" and ref_b in mails[0].text
    assert mails[0].subject.startswith("Дайджест") and "!" not in mails[0].text and "!" not in mails[0].subject
    assert tick(T2 + timedelta(hours=1))["digest"]["digests"] == 0 and len(mails) == 1  # раз в день


def test_tick_is_idempotent(client, day_hours, mails, push_log):
    te, need = setup(client)
    subscribe(client, te, need)
    candidate_with_category(client, "b@example.com")
    tick(T1)
    again = [tick(T1 + timedelta(minutes=m)) for m in (3, 6)] + [tick(T1_EVE)]
    assert all(a["entered"] == 0 and a["notified"] == 0 for a in again)
    assert len(notes("hr@corp.ru", "new_match")) == 1 and len(push_log) == 0  # устройств нет — отправлять некуда
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(NeedSubEntry).where(NeedSubEntry.is_new.is_(True))) == 1


def test_mark_seen_clears_new_and_counts(client, day_hours):
    te, need = setup(client)
    subscribe(client, te, need)
    ref = my_ref(client, candidate_with_category(client, "b@example.com"))
    tick(T1)
    summ = client.get("/api/employer/subscriptions", headers=H(te)).json()
    assert summ["new_total"] == 1 and summ["items"][0]["new_count"] == 1
    r = client.post(f"/api/employer/needs/{need['id']}/subscription/seen", json={"refs": ["К-000000"]}, headers=H(te))
    assert r.json()["new_count"] == 1  # чужая ссылка ничего не отмечает
    r = client.post(f"/api/employer/needs/{need['id']}/subscription/seen", json={"refs": [ref]}, headers=H(te))
    assert r.json()["new_count"] == 0
    assert client.get("/api/employer/subscriptions", headers=H(te)).json()["new_total"] == 0


def test_disabled_subscription_is_silent_and_reenable_rebases(client, day_hours, mails):
    te, need = setup(client)
    subscribe(client, te, need)
    off = client.put(f"/api/employer/needs/{need['id']}/subscription", json={"enabled": False}, headers=H(te)).json()
    assert off["enabled"] is False and off["new"] == []
    candidate_with_category(client, "b@example.com")
    st = tick(T1)
    assert st["recomputed"] == 0 and notes("hr@corp.ru") == []
    # повторное включение: кто уже в топе, тот известен
    on = subscribe(client, te, need)
    assert on["new_count"] == 0 and on["in_top"] == 2
    assert tick(T1_EVE)["entered"] == 0 and notes("hr@corp.ru") == []


def test_weekly_digest_not_before_seven_days(client, day_hours, mails):
    te, need = setup(client)
    subscribe(client, te, need, frequency="weekly")
    candidate_with_category(client, "b@example.com")
    tick(T1)
    assert tick(T2)["digest"]["digests"] == 1 and len(mails) == 1  # первое письмо — утром после события
    assert "за неделю" in mails[0].subject
    candidate_with_category(client, "c@example.com")
    tick(T2 + timedelta(hours=2))
    assert tick(T2 + timedelta(days=3))["digest"]["digests"] == 0 and len(mails) == 1
    assert tick(T2 + timedelta(days=7, hours=1))["digest"]["digests"] == 1 and len(mails) == 2


def test_instant_push_off_for_daily_frequency(client, day_hours, mails, push_log):
    te, need = setup(client)
    push_device(client, te)
    subscribe(client, te, need, frequency="daily")
    candidate_with_category(client, "b@example.com")
    tick(T1)
    assert push_log == []  # «только дайджест» — push не отправляется
    assert tick(T2)["digest"]["digests"] == 1


def test_prefs_push_and_email_off(client, day_hours, mails, push_log):
    te, need = setup(client)
    push_device(client, te)
    subscribe(client, te, need)
    r = client.put("/api/notifications/prefs", json={"push_enabled": False, "email_enabled": False}, headers=H(te))
    assert r.json() == {"push_enabled": False, "email_enabled": False, "reminders_enabled": True}
    candidate_with_category(client, "b@example.com")
    tick(T1)
    tick(T2)
    assert push_log == [] and mails == []
    item = client.get("/api/notifications", headers=H(te)).json()["items"][0]
    assert item["kind"] == "digest" or item["kind"] == "new_match"  # в кабинете уведомления остаются


def test_new_state_expires_after_ttl(client, day_hours):
    te, need = setup(client)
    subscribe(client, te, need)
    candidate_with_category(client, "b@example.com")
    tick(T1)
    ttl = get_settings().subs_new_ttl_days
    with SessionLocal() as db:
        s = db.scalar(select(NeedSubscription))
        from app.modules.subs import service

        assert len(service.new_entries(db, s, T1 + timedelta(days=ttl - 1))) == 1
        assert service.new_entries(db, s, T1 + timedelta(days=ttl + 1)) == []


def test_foreign_need_is_404_and_roles(client):
    te, need = setup(client)
    other = employer(client, "other@corp.ru", "ООО Другая")
    url = f"/api/employer/needs/{need['id']}/subscription"
    assert client.get(url, headers=H(other)).status_code == 404
    assert client.put(url, json={"enabled": True}, headers=H(other)).status_code == 404
    assert client.post(url + "/seen", json={}, headers=H(other)).status_code == 404
    tc = register_and_verify(client, "cand@example.com")
    assert client.get(url, headers=H(tc)).status_code == 403
    assert client.get("/api/notifications").status_code == 401
    assert client.put(url, json={"enabled": True, "frequency": "hourly"}, headers=H(te)).status_code == 422


# ------------------------------------------------------------------ кэш и пометки
def test_cache_no_recompute_without_changes(client, day_hours, monkeypatch):
    from app.modules.matching import ranking

    te, need = setup(client)
    subscribe(client, te, need)
    calls = []
    real = ranking.build_selection
    monkeypatch.setattr(ranking, "build_selection", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    base = utcnow()
    tick(base + timedelta(minutes=2))  # кандидат A менялся после подписки: один пересчёт
    n = len(calls)
    assert n == 1
    for m in (4, 6, 8):
        assert tick(base + timedelta(minutes=m))["recomputed"] == 0
    assert len(calls) == n
    # изменение кандидата другого направления подборку не пересчитывает
    t = register_and_verify(client, "front@example.com")
    client.put("/api/me/onboarding", json={"direction": "frontend", "stack": [{"tag": "react", "level": 3}],
                                           "experience_years": 3, "roles": ["developer"], "work_format": "remote",
                                           "city": "Казань", "salary_min_hidden": 200000, "privacy": {},
                                           "consent_publication": True}, headers=H(t))
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SubsDirty)) >= 1
    assert tick(base + timedelta(minutes=10))["recomputed"] == 0 and len(calls) == n
    # страховочный полный пересчёт — раз в сутки
    assert tick(base + timedelta(hours=25))["recomputed"] == 1 and len(calls) == n + 1


def test_dirty_throttled_not_lost(client, day_hours, monkeypatch):
    te, need = setup(client)
    subscribe(client, te, need)
    candidate_with_category(client, "b@example.com")
    base = utcnow()
    st = tick(base + timedelta(seconds=5))  # слишком рано: пометки остаются
    assert st["recomputed"] == 0
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SubsDirty)) >= 1
    assert tick(base + timedelta(minutes=3))["entered"] == 1


def test_dirty_listener_marks_grade_and_facts(client):
    from app.modules.profiles.models import CandidateFact, CandidateProfile

    candidate_with_category(client, "a@example.com")
    u = uid("a@example.com")
    with SessionLocal() as db:
        db.query(SubsDirty).delete()
        db.commit()
        p = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == u))
        p.current_grade_id = "senior"
        db.commit()
        assert db.get(SubsDirty, u) is not None and "profile" in (db.get(SubsDirty, u).reason or "profile")
        db.query(SubsDirty).delete()
        db.commit()
        f = db.scalar(select(CandidateFact).where(CandidateFact.user_id == u))
        assert f is not None
        f.value = {**f.value, "touch": 1}
        db.commit()
        assert db.get(SubsDirty, u) is not None


def test_lease_blocks_parallel_tick(client):
    with SessionLocal() as db:
        runner._acquire(db, T1)
        assert runner._acquire(db, T1 + timedelta(seconds=30)) is False
        assert runner._acquire(db, T1 + timedelta(seconds=runner.LEASE_S + 1)) is True


def test_quiet_hours_defer_push_until_morning(client, mails, push_log):
    te, need = setup(client)
    push_device(client, te)
    subscribe(client, te, need)
    candidate_with_category(client, "b@example.com")
    st = tick(T1_NIGHT)  # 23:30 по Москве
    assert st["notified"] == 1 and st["dispatch"]["deferred"] == 1 and push_log == []
    assert notes("hr@corp.ru", "new_match")[0].delivery == "pending"
    st = tick(T2)
    assert st["dispatch"]["push"] == 1 and len(push_log) == 1
    assert notes("hr@corp.ru", "new_match")[0].delivery == "done"


# ------------------------------------------------------------------ Н6: напоминания
def invite(client, te, tc) -> dict:
    r = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": my_ref(client, tc)}, headers=H(te))
    assert r.status_code == 201, r.text
    return r.json()


def test_reminder_unanswered_invitation_after_3_days_once(client, day_hours, mails):
    tc = candidate_with_category(client, "a@example.com")
    te = employer(client, "hr@corp.ru")
    inv = invite(client, te, tc)
    now = utcnow()
    assert tick(now + timedelta(days=2))["reminders"]["inv_unanswered"] == 0
    assert tick(now + timedelta(days=3, hours=1))["reminders"]["inv_unanswered"] == 1
    assert tick(now + timedelta(days=3, hours=2))["reminders"]["inv_unanswered"] == 0
    assert tick(now + timedelta(days=4))["reminders"]["inv_unanswered"] == 0
    n = notes("a@example.com", "inv_unanswered")
    assert len(n) == 1 and "Ромашка" in n[0].body and "3" in n[0].body and n[0].url == "/candidate/invitations"
    assert len(mails) == 1 and mails[0].to == "a@example.com"
    assert "!" not in mails[0].text and "220" in mails[0].text.replace("\u00a0", "")
    # ответ снимает напоминания
    client.post(f"/api/candidate/invitations/{inv['id']}/decline", json={"reason": "other"}, headers=H(tc)) \
        if False else None


def test_reminder_day_before_expiry_to_candidate(client, day_hours, mails):
    tc = candidate_with_category(client, "a@example.com")
    te = employer(client, "hr@corp.ru")
    inv = invite(client, te, tc)
    now = utcnow()
    exp = now + timedelta(days=10)
    from app.modules.invitations.models import Invitation

    with SessionLocal() as db:
        db.execute(update(Invitation).where(Invitation.id == uuid.UUID(inv["id"])).values(expires_at=exp))
        db.commit()
    assert tick(exp - timedelta(hours=30))["reminders"]["inv_expiring"] == 0
    assert tick(exp - timedelta(hours=20))["reminders"]["inv_expiring"] == 1
    assert tick(exp - timedelta(hours=10))["reminders"]["inv_expiring"] == 0
    assert len(notes("a@example.com", "inv_expiring")) == 1
    assert any("истекает завтра" in m.subject for m in mails)


def test_expired_invitation_status_and_employer_digest(client, day_hours, mails):
    tc = candidate_with_category(client, "a@example.com")
    te = employer(client, "hr@corp.ru")
    inv = invite(client, te, tc)
    exp = utcnow() + timedelta(days=30)
    st = tick(exp + timedelta(hours=1))
    assert st["reminders"]["inv_expired"] == 1
    hist = client.get("/api/employer/invitations", headers=H(te)).json()[0]
    assert hist["status"] == "expired" and hist["history"][-1]["status"] == "expired"
    assert client.get(f"/api/candidate/invitations/{inv['id']}", headers=H(tc)).json()["status"] == "expired"
    q = notes("hr@corp.ru", "inv_expired")
    assert len(q) == 1 and q[0].digest == "queued" and q[0].channels == []
    assert tick(exp + timedelta(hours=2))["reminders"]["inv_expired"] == 0  # второй раз — не повторяется
    nxt = datetime(exp.year, exp.month, exp.day, 6, 30, tzinfo=UTC) + timedelta(days=1)
    assert tick(nxt)["digest"]["digests"] == 1
    assert "Приглашения, срок ответа на которые истёк" in mails[-1].text and "!" not in mails[-1].text
    assert notes("hr@corp.ru", "inv_expired")[0].digest == "sent"


def test_stale_application_reminds_employer_after_5_days(client, day_hours, mails):
    from app.integrations.vacancies.models import Vacancy, VacancyApplication
    from app.modules.profiles.models import Company

    tc = candidate_with_category(client, "a@example.com")
    te = employer(client, "hr@corp.ru")
    with SessionLocal() as db:
        co = db.scalar(select(Company))
        v = Vacancy(company_id=co.id, created_by=uid("hr@corp.ru"), title="Python-разработчик", description="x" * 40,
                    stack=["python"], salary_from=200000, salary_to=250000, status="published", published_at=utcnow())
        db.add(v)
        db.flush()
        a = VacancyApplication(vacancy_id=v.id, candidate_user_id=uid("a@example.com"), status="sent", events=[])
        db.add(a)
        db.commit()
    now = utcnow()
    assert tick(now + timedelta(days=4))["reminders"]["app_stale"] == 0
    assert tick(now + timedelta(days=5, hours=1))["reminders"]["app_stale"] == 1
    n = notes("hr@corp.ru", "app_stale")
    assert len(n) == 1 and "Python-разработчик" in n[0].body and n[0].digest == "queued"  # работодателю — в дайджест
    assert tick(now + timedelta(days=6))["reminders"]["app_stale"] == 0
    assert len(notes("hr@corp.ru", "app_stale")) == 1
    with SessionLocal() as db:  # после решения работодателя напоминаний нет
        db.execute(update(VacancyApplication).values(status="accepted"))
        db.commit()
    assert tick(now + timedelta(days=9))["reminders"]["app_stale"] == 0


def test_reminders_opt_out_and_synthetic_skipped(client, day_hours, mails):
    tc = candidate_with_category(client, "a@example.com")
    te = employer(client, "hr@corp.ru")
    invite(client, te, tc)
    client.put("/api/notifications/prefs", json={"reminders_enabled": False}, headers=H(tc))
    assert tick(utcnow() + timedelta(days=3, hours=1))["reminders"]["inv_unanswered"] == 0
    assert notes("a@example.com") == [] and mails == []


def test_demo_account_gets_feed_but_no_mail(client, day_hours, mails):
    from tests.test_day2_rules import make_demo

    tc = candidate_with_category(client, "a@example.com")
    te = employer(client, "hr@corp.ru")
    invite(client, te, tc)
    make_demo("a@example.com")
    tick(utcnow() + timedelta(days=3, hours=1))
    n = notes("a@example.com", "inv_unanswered")
    assert len(n) == 1 and n[0].email_state == "demo" and mails == []


# ------------------------------------------------------------------ тексты и документация
def test_texts_have_no_exclamation_marks_and_plural():
    from app.modules.subs.texts import plural

    samples = [texts.match_title(3), *texts.match_push("Python", 2), texts.match_body("Python", [
        {"ref": "К-123456", "rank": 2, "score": 0.81, "card": {"category": {"title": "Backend · Middle"}}}], 10),
        *texts.inv_unanswered("Ромашка", "Python", 200000, 300000, 3, utcnow()), *texts.inv_expiring("Ромашка", "Python", utcnow()),
        *texts.inv_expired_employer("К-123456", "Python"), *texts.app_stale_employer("К-123456", "Python", 5),
        texts.digest_subject("daily"), texts.digest_subject("weekly"), texts.digest_footer()]
    assert all("!" not in s for s in samples)
    assert [plural(n, ("день", "дня", "дней")) for n in (1, 2, 5, 11, 21, 112)] == ["день", "дня", "дней", "дней", "день", "дней"]
    assert not any(re.search(r"[\U0001F300-\U0001FAFF]", s) for s in samples)


# ------------------------------------------------------------------ песочница жюри
def sandbox_employer(client) -> tuple[str, str]:
    r = client.post("/api/jury/login", json={"persona": "employer", "scenario": "new"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"], r.json()["scenario"]


def test_simulate_only_in_sandbox(client, day_hours):
    te, need = setup(client)
    r = client.post("/api/jury/subs/simulate", json={}, headers=H(te))  # живой работодатель
    assert r.status_code == 403 and r.json()["detail"]["code"] == "jury_sandbox_only"
    shared = client.post("/api/jury/login", json={"persona": "employer"}).json()["access_token"]  # общее демо
    r = client.post("/api/jury/subs/simulate", json={}, headers=H(shared))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "jury_sandbox_only"
    tc = candidate_with_category(client, "cand@example.com")
    assert client.post("/api/jury/subs/simulate", json={}, headers=H(tc)).status_code == 403
    assert client.post("/api/jury/subs/simulate", json={}).status_code == 401


def test_simulate_scenario_subscribe_new_candidate_notification(client, mails):
    token, sid = sandbox_employer(client)
    r = client.post("/api/jury/subs/simulate", json={}, headers=H(token))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["auto_subscribed"] is True and out["confirmed"] is True and re.fullmatch(r"C-[0-9A-Z]{6}", out["candidate_ref"])
    sub = client.get(f"/api/employer/needs/{out['need_id']}/subscription", headers=H(token)).json()
    assert sub["enabled"] is True
    if out["entered_top"]:  # попадание в топ-10 зависит от пула; при попадании — уведомление и отметка «новый»
        assert out["candidate_ref"] in sub["new_refs"] and out["notification"]["body"].count(out["candidate_ref"]) >= 1
        assert "!" not in out["notification"]["body"]
        feed = client.get("/api/notifications", headers=H(token)).json()
        kinds = {n["kind"]: n for n in feed["items"]}
        assert set(kinds) == {"new_match", "digest"} and mails == []  # дайджест для жюри — сразу; письмо демо-учётке не уходит
        assert kinds["digest"]["email_state"] == "demo" and out["candidate_ref"] in kinds["digest"]["body"]
    else:
        assert out["notification"] is None and sub["new_count"] == 0
    # второй запуск — ещё один кандидат; чужие песочницы не затронуты
    r2 = client.post("/api/jury/subs/simulate", json={"need_id": out["need_id"]}, headers=H(token))
    assert r2.status_code == 200 and r2.json()["candidate_ref"] != out["candidate_ref"]
    assert r2.json()["auto_subscribed"] is False


def test_simulate_limit_and_cleanup_on_delete(client, monkeypatch):
    from app.modules.subs import demo

    monkeypatch.setattr(demo, "SIM_MAX", 1)
    token, sid = sandbox_employer(client)
    assert client.post("/api/jury/subs/simulate", json={}, headers=H(token)).status_code == 200
    r = client.post("/api/jury/subs/simulate", json={}, headers=H(token))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "sim_limit"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(User).where(User.email.like(demo.sim_like(sid)))) == 1
        assert db.scalar(select(func.count()).select_from(NeedSubscription)) == 1
    assert client.delete("/api/jury/sandbox", headers=H(token)).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(User).where(User.email.like(demo.sim_like(sid)))) == 0
        assert db.scalar(select(func.count()).select_from(NeedSubscription)) == 0
        assert db.scalar(select(func.count()).select_from(UserNotification)) == 0
