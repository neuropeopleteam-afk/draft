"""Ф4 «Интерфейс: подписи и мелочи»: демо-сведения ФНС и индекс доверия демо-работодателей, состояние передачи в ATS
по системам в карточке приглашения, подписи («other», повтор места в кубке), формат «лёгкий труд» только для 16–17 лет."""
from __future__ import annotations

from types import SimpleNamespace

from app.core.fmt import probe_title
from app.integrations.egrul import demo as egrul_demo
from app.integrations.egrul import trust as trust_mod
from app.modules.catalog.seed_data import tag_title
from app.modules.fsp.youth import check_offer, employment_safety
from tests.test_ats_providers import (_accepted, _company_of, ats_http, http, po_client)  # noqa: F401 — фикстуры
from tests.test_ats_stages import _move, _pipeline, _sync
from tests.test_day2_rules import H, candidate_with_category, employer


# ------------------------------------------------------------------ демо-сведения ФНС и индекс доверия

def _demo_company(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, is_demo=True, inn=None)


def test_demo_registry_good_and_bad_pure():
    f, summary, preliminary, critical = trust_mod.registry_factors(None, _demo_company("Демо жюри: Северный платёж"))
    assert [x["status"] for x in f] == ["ok", "ok", "ok"] and sum(x["points"] for x in f) == 50
    assert summary["status"] == "demo_found" and summary["demo"] is True and "демо" in summary["note"]
    assert "демо" in f[0]["title"].lower() and "демо" in f[0]["text"].lower()
    assert not preliminary and not critical
    # дата регистрации не меняется между запросами и лежит в диапазоне 2015–2021
    assert summary["registered_at"] == egrul_demo.registered_at("Демо жюри: Северный платёж")
    assert "2015-03-01" <= summary["registered_at"] <= "2021-12-31"

    f, summary, preliminary, critical = trust_mod.registry_factors(None, _demo_company("Демо жюри: Быстрый заработок"))
    assert f[0]["status"] == "bad" and critical and summary["status"] == "demo_not_found"
    assert sum(x["points"] for x in f) == 0


def test_jury_sandbox_employers_trust_good_and_bad(client):
    """Песочница жюри: «Северный платёж» и «Логистика Онлайн» — высокий индекс, «Быстрый заработок» — низкий."""
    from app.modules.jury import scope

    r = client.post("/api/jury/login", json={"persona": "employer", "scenario": "new"})
    assert r.status_code == 200, r.text
    te = r.json()["access_token"]
    t = client.get("/api/employer/company/trust", headers=H(te)).json()
    assert t["level"] == "high" and t["score"] >= 90 and t["demo"] is True and not t["preliminary"]
    by = {f["id"]: f for f in t["factors"]}
    assert by["registry"]["status"] == "ok" and "демо" in by["registry"]["title"].lower()
    assert by["email"]["status"] == "ok" and "jury.example.com" in by["email"]["text"]
    assert t["registry"]["status"] == "demo_found" and t["registry"]["demo"] is True
    # вилки демо-приглашений в рынке: интерн-кандидаты в демо-приглашения общего демо не попадают
    assert "вне рынка" not in by["salary"]["text"]

    sid = scope.parse(client.get("/api/me", headers=H(te)).json()["email"])[1]
    tm = client.post("/api/jury/login", json={"persona": "candidate", "scenario": sid}).json()["access_token"]
    invs = client.get("/api/candidate/invitations", headers=H(tm)).json()
    names = {i["company"]["name"]: i["id"] for i in invs}
    assert {"Демо жюри: Логистика Онлайн", "Демо жюри: Быстрый заработок"} <= set(names)
    short = client.get("/api/candidate/invitations-trust", headers=H(tm)).json()
    good = short[names["Демо жюри: Логистика Онлайн"]]
    bad = short[names["Демо жюри: Быстрый заработок"]]
    assert good["level"] == "high" and good["demo"] is True
    assert bad["level"] == "low" and bad["critical"] is True and bad["score"] <= 10
    full = client.get(f"/api/candidate/invitations/{names['Демо жюри: Быстрый заработок']}/trust", headers=H(tm)).json()
    assert any(f["id"] == "registry" and f["status"] == "bad" for f in full["factors"])
    assert full["offer_salary"]["status"] == "warn"  # вилка 600–850 тыс. ₽ Backend · Middle — «приманка»
    # ровно одно приглашение «Python-разработчик (сервис маршрутов)» у Марии (test_fixes_0710) — плохая компания его не дублирует
    assert sum(1 for i in invs if i["position_title"] == "Python-разработчик (сервис маршрутов)") == 1


def test_demo_site_stub_and_bad_company_email_factor(client):
    """Сайт-заглушка .invalid у демо-компании не даёт «несовпадения домена»; у «плохой» компании почта не совпадает."""
    from app.core.db import SessionLocal
    from app.modules.profiles.models import Company

    with SessionLocal() as db:
        ok = Company(name="Демо: ФинТех Север", is_demo=True, website="https://example.invalid", contact_email="hr@fintech.example.com")
        bad = Company(name="Демо: Студия Интерфейсов", is_demo=True, contact_email="hr-09@demo.invalid")
        for c in (ok, bad):
            db.add(c)
        db.flush()
        e_ok, e_bad = trust_mod.email_factor(db, ok), trust_mod.email_factor(db, bad)
        db.rollback()
    assert e_ok["status"] == "ok" and e_ok["points"] == 15
    assert e_bad["status"] == "warn" and e_bad["points"] == 0


# ------------------------------------------------------------------ подписи

def test_other_topic_never_shown_raw():
    assert tag_title("other") == "Прочие темы"
    assert tag_title("python") == "Python" and tag_title("неизвестный-тег") == "неизвестный-тег"


def test_probe_title_without_repeated_place():
    # старые факты кубка хранили место и в названии, и в вердикте
    assert probe_title("Кубок «Надёжные платежи»: 2 место из 6", "2 место из 6") == "Кубок «Надёжные платежи»"
    assert probe_title("Кубок «Надёжные платежи» — 2 место из 6", "2 место из 6") == "Кубок «Надёжные платежи»"
    # новые — только в вердикте: название не меняется
    assert probe_title("Кубок «Надёжные платежи»", "2 место из 6") == "Кубок «Надёжные платежи»"
    assert probe_title("Зонд по платежам", "Сильное решение") == "Зонд по платежам"
    assert probe_title(None, None) == ""


# ------------------------------------------------------------------ формат предложения

def test_light_work_only_for_minors():
    adult = SimpleNamespace(age_group="18+", parental_consent=False)
    teen = SimpleNamespace(age_group="16-17", parental_consent=True)
    assert employment_safety(adult)["allowed_formats"] == ["employment", "internship"]
    assert employment_safety(teen)["allowed_formats"] == ["internship", "light_work"]
    check_offer(adult, {"format": "employment"})
    check_offer(adult, {"format": "internship"})
    try:
        check_offer(adult, {"format": "light_work", "reduced_time": True})
    except Exception as e:  # noqa: BLE001
        assert getattr(e, "status_code", None) == 422 and "16–17" in str(getattr(e, "detail", ""))
    else:
        raise AssertionError("лёгкий труд взрослому кандидату должен отклоняться")
    check_offer(teen, {"format": "light_work", "reduced_time": True, "employer_acknowledged": True})


# ------------------------------------------------------------------ ATS: состояние по системам

def test_invitation_ats_transfers_per_system(client, ats_http, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.integrations.push.service.send_to_user", lambda *a, **k: 0)
    tc, te, inv = _accepted(client)
    emp_inv = lambda: next(i for i in client.get("/api/employer/invitations", headers=H(te)).json() if i["id"] == inv["id"])  # noqa: E731
    assert emp_inv()["ats_transfers"] == []  # приглашение ещё не принято — передавать нечего
    assert client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc)).status_code == 200
    assert emp_inv()["ats_transfers"] == []  # принято, но ни одной ATS не подключено

    assert client.post("/api/employer/ats/providers/potok/demo", headers=H(te)).status_code == 200
    assert [(x["target"], x["state"]) for x in emp_inv()["ats_transfers"]] == [("potok", "not_sent")]

    r = client.post("/api/employer/ats/push", json={"invitation_id": inv["id"]}, headers=H(te))
    assert r.status_code == 200, r.text
    (potok,) = emp_inv()["ats_transfers"]
    assert potok["target"] == "potok" and potok["title"] == "Поток" and potok["state"] == "sent" and potok["error"] is None
    # этап сразу после передачи — «Новые» (из ответа «Потока»), без ожидания опроса обратного канала
    assert potok["stage"]["name"] == "Новые" and potok["stage"]["synced"] is False

    # обратный канал: рекрутёр двигает кандидата — этап в строке «Передано» обновляется
    join = _pipeline(client, te)[0]["join_id"]
    _move(client, te, join, "interview_client")
    assert _sync(client, te)["changed"] == 1
    st = emp_inv()["ats_transfers"][0]["stage"]
    assert st["name"] == "Интервью" and st["stage"] == "interview" and st["synced"] is True

    # кандидату состояние передачи не показывается
    cand = next(i for i in client.get("/api/candidate/invitations", headers=H(tc)).json() if i["id"] == inv["id"])
    assert "ats_transfers" not in cand
