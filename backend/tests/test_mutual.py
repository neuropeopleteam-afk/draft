"""Взаимный подбор (Н9), обратная связь по подборке (Н2), ссылка для нанимающего руководителя (Н3)."""
from datetime import timedelta
import json

from sqlalchemy import select, update

from app.core.db import SessionLocal, utcnow
from app.modules.mutual import fit as fitm
from tests.conftest import register_and_verify
from tests.test_day2_rules import H, INVITE, candidate_with_category, employer, my_ref

NEED = ("Нужен middle Python-разработчик в платёжный сервис: FastAPI, PostgreSQL, интеграции с банками. "
        "Удалённо, зарплата 240 000 – 300 000 ₽.")
SECRET_MINIMA = ("250000", "250 000", "250\u00a0000", "400000", "400 000", "400\u00a0000")


def _world(client):
    """Три кандидата backend.middle с разными условиями и работодатель с потребностью «удалённо, до 300 000»."""
    t1 = candidate_with_category(client, "c1@example.com")  # удалёнка, Казань, минимум 250 000
    t2 = candidate_with_category(client, "c2@example.com", work_format="office", city="Москва",
                                 salary_min_hidden=400000)
    t3 = candidate_with_category(client, "c3@example.com", salary_min_hidden=200000)
    te = employer(client)
    r = client.post("/api/employer/needs", json={"text": NEED}, headers=H(te))
    assert r.status_code == 201, r.text
    need = r.json()
    return {"t": [t1, t2, t3], "refs": [my_ref(client, t) for t in (t1, t2, t3)], "te": te, "need": need}


def _sel(client, w, v=1):
    r = client.get(f"/api/employer/needs/{w['need']['id']}/selections/{v}", headers=H(w["te"]))
    assert r.status_code == 200, r.text
    return r.json()


def _mutual(client, w, v=1):
    r = client.get(f"/api/employer/needs/{w['need']['id']}/selections/{v}/mutual", headers=H(w["te"]))
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ чистая логика индикатора

BASE = dict(work_format="remote", city="Казань", relocation=False, salary_min=250000, privacy={},
            declared_stack={"python", "fastapi", "postgresql"}, prefs=None, need_text=NEED)
REQ = {"work_format": "remote", "salary_to": 300000,
       "stack_required": [{"tag": "python", "weight": 1}, {"tag": "fastapi", "weight": 1}],
       "stack_desired": [{"tag": "postgresql", "weight": 0.5}]}


def test_fit_levels_and_caps_pure():
    ok = fitm.offer_fit(**BASE, req=REQ, salary_to=300000)
    assert ok["level"] == "high" and ok["title"] == "Предложение подходит кандидату" and not ok["decline_risk"]
    low = fitm.offer_fit(**BASE, req=REQ, salary_to=200000)
    assert low["level"] == "low" and low["decline_risk"] and low["line"].startswith("Верх вилки ниже ожиданий")
    office = fitm.offer_fit(**{**BASE, "work_format": "remote"}, req={**REQ, "work_format": "office", "city": "Москва"},
                            salary_to=300000)
    assert office["level"] == "low" and "в предложении — офис" in office["line"]
    reloc = fitm.offer_fit(**{**BASE, "work_format": "hybrid", "relocation": True},
                           req={**REQ, "work_format": "hybrid", "city": "Москва"}, salary_to=300000)
    assert {f["key"]: f["status"] for f in reloc["factors"]}["location"] == "partial" and reloc["level"] == "medium"
    # «сейчас не ищу» — не выше «частично»; явные интересы важнее стека из опроса
    nl = fitm.offer_fit(**{**BASE, "prefs": {"offers_status": "not_looking", "interest_tags": ["go"]}}, req=REQ,
                        salary_to=300000)
    by = {f["key"]: f for f in nl["factors"]}
    assert nl["level"] == "medium" and by["readiness"]["status"] == "bad" and by["stack"]["status"] == "bad"
    # мало данных: ни формата, ни вилки, ни стека — уровень «мало данных», а не «вероятно, откажет»
    none = fitm.offer_fit(**BASE, req={}, salary_to=None)
    assert none["level"] == "unknown" and none["score"] is None


def test_fit_privacy_and_hidden_minimum_pure():
    hidden = fitm.offer_fit(**{**BASE, "privacy": {"show_city": False, "show_work_format": False, "show_stack": False},
                               "prefs": {"salary_signal": False}},
                            req={**REQ, "work_format": "office", "city": "Москва"}, salary_to=200000)
    st = {f["key"]: f["status"] for f in hidden["factors"]}
    assert st["format"] == st["location"] == st["stack"] == st["salary"] == "hidden"
    # работодателю — только «в ожиданиях / ниже ожиданий», без чисел минимума; кандидату — его минимум
    for salary_to in (200000, 249000, 250000, 300000):
        out = json.dumps(fitm.offer_fit(**BASE, req=REQ, salary_to=salary_to), ensure_ascii=False)
        assert not any(s in out for s in SECRET_MINIMA)
    me = fitm.offer_fit(**BASE, req=REQ, salary_to=200000, audience="candidate")
    assert "ниже вашего минимума 250\u00a0000\u00a0₽" in me["line"]
    # минимум сравнивается с точностью до 10 000 ₽: ответ зависит только от «корзины» верха вилки
    assert fitm.rounded_minimum(255000) == 260000 and fitm.salary_bucket(259999) == 25
    lim = fitm.offer_fit(**BASE, req=REQ, salary_to=300000, salary_limited=True)
    assert {f["key"]: f["status"] for f in lim["factors"]}["salary"] == "limited"


def test_detect_tasks_with_quotes():
    t = {x["id"]: x["quote"] for x in fitm.detect_tasks(NEED)}
    assert t["payments"].lower().startswith("платёж") and t["integrations"].lower().startswith("интеграц")
    assert "ml" not in t  # «ml» ищется только целым словом
    assert fitm.detect_tasks("Разработка UI-кита и дизайн-системы")[0]["id"] == "product_ui"
    assert fitm.detect_tasks(None) == []


# ------------------------------------------------------------------ подборка: индикатор и порядок

def test_selection_indicator_default_order_unchanged(client):
    w = _world(client)
    before = [r["ref"] for r in _sel(client, w)["results"]]
    assert set(w["refs"]) <= set(before)
    t3 = w["t"][2]
    r = client.put("/api/candidate/preferences", headers=H(t3),
                   json={"offers_status": "not_looking", "interest_tags": ["go"], "interest_tasks": ["ml"]})
    assert r.status_code == 200, r.text
    m = _mutual(client, w)
    c1, c2, c3 = (m["items"][x] for x in w["refs"])
    assert c1["level"] == "high", c1
    assert c2["level"] == "low" and c2["decline_risk"] and "ниже ожиданий" in c2["line"], c2
    assert c3["level"] in ("medium", "low") and "Сейчас не ищет" in json.dumps(c3, ensure_ascii=False)
    assert m["algorithm"] == "mutual-v1" and sum(m["counts"].values()) == len(m["items"])
    raw = json.dumps(m, ensure_ascii=False)
    assert not any(s in raw for s in SECRET_MINIMA), "скрытый минимум не должен уходить работодателю"
    # порядок по умолчанию (match-v1) не изменился от интересов кандидатов; «с учётом интереса» — отдельный список
    assert [r["ref"] for r in _sel(client, w)["results"]] == before
    order = m["mutual_order"]
    assert sorted(order) == sorted(before) and order.index(w["refs"][1]) > order.index(w["refs"][0])


def test_exclude_filter_is_noop_by_default(client):
    """Guard: без exclude_refs выдача match-v1 идентична; с ним — только сужается."""
    from app.modules.matching import ranking

    w = _world(client)
    req = w["need"]["requirements"]
    with SessionLocal() as db:
        a = ranking.build_selection(db, req, {})["results"]
        b = ranking.build_selection(db, req, {"exclude_refs": []})["results"]
        c = ranking.build_selection(db, req, {"exclude_refs": [w["refs"][0]]})["results"]
    key = lambda rs: [(r["ref"], r["rank"], r["score"]) for r in rs]  # noqa: E731
    assert key(a) == key(b)
    assert [r["ref"] for r in c] == [r["ref"] for r in a if r["ref"] != w["refs"][0]]


# ------------------------------------------------------------------ форма приглашения: подсказка до отправки

def test_offer_check_hint_limit_and_signal(client):
    w = _world(client)
    te, ref1, nid = w["te"], w["refs"][0], w["need"]["id"]

    def check(to, ref=ref1):
        r = client.post("/api/employer/mutual/offer-check", headers=H(te),
                        json={"candidate_ref": ref, "need_id": nid, "salary_from": 150000, "salary_to": to})
        assert r.status_code == 200, r.text
        assert not any(s in r.text for s in SECRET_MINIMA)
        return r.json()

    low = check(200000)
    assert low["salary_status"] == "bad" and "вероятно, откажет" in low["hint"] and low["level"] == "low"
    assert check(300000)["salary_status"] == "ok"
    assert check(205000)["salary_status"] == "bad"  # та же корзина 200 000 — без расхода лимита
    for to in (210000, 220000, 230000):
        assert check(to)["salary_status"] == "bad"
    limited = check(240000)  # шестая корзина за сутки
    assert limited["salary_status"] == "limited" and limited["checks_left"] is None
    assert check(300000)["salary_status"] == "ok"  # уже проверенная корзина — доступна
    # кандидат запретил сообщать о вилке — работодатель видит «не сообщает»
    client.put("/api/candidate/preferences", headers=H(w["t"][1]), json={"salary_signal": False})
    assert check(300000, w["refs"][1])["salary_status"] == "hidden"
    r = client.post("/api/employer/mutual/offer-check", headers=H(te),
                    json={"candidate_ref": "K-NOPE00", "salary_to": 100000})
    assert r.status_code == 404
    r = client.post("/api/employer/mutual/offer-check", headers=H(te),
                    json={"candidate_ref": ref1, "salary_from": 300000, "salary_to": 200000})
    assert r.status_code == 422


# ------------------------------------------------------------------ Н2: отзывы, новая версия, «ещё похожих»

def test_feedback_refine_keeps_previous_version(client):
    w = _world(client)
    te, nid = w["te"], w["need"]["id"]
    ref1, ref2 = w["refs"][0], w["refs"][1]
    url = f"/api/employer/needs/{nid}/feedback"
    r = client.put(url, headers=H(te), json={"ref": ref2, "version": 1, "verdict": "unfit"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "reason_required"
    r = client.post(f"/api/employer/needs/{nid}/selections/1/refine", headers=H(te))
    assert r.status_code == 409
    r = client.put(url, headers=H(te), json={"ref": ref2, "version": 1, "verdict": "unfit", "reason": "format",
                                             "comment": "Только офис"})
    assert r.status_code == 200 and r.json()["reason_title"] == "формат", r.text
    assert client.put(url, headers=H(te), json={"ref": ref1, "version": 1, "verdict": "fit"}).status_code == 200
    assert client.put(url, headers=H(te), json={"ref": "K-NOPE00", "version": 1, "verdict": "fit"}).status_code == 404
    fb = _mutual(client, w)["feedback"]
    assert fb[ref2]["verdict"] == "unfit" and fb[ref1]["verdict"] == "fit"
    r = client.post(f"/api/employer/needs/{nid}/selections/1/refine", headers=H(te))
    assert r.status_code == 201, r.text
    v2 = r.json()
    refs2 = [x["ref"] for x in v2["results"]]
    assert v2["version"] == 2 and v2["parent_version"] == 1 and ref2 not in refs2 and ref1 in refs2
    assert v2["filters"]["exclude_refs"] == [ref2] and v2["filters"]["origin"]["kind"] == "feedback"
    assert "формат" in v2["filters"]["origin"]["note"]
    assert ref2 in [x["ref"] for x in _sel(client, w, 1)["results"]], "прежняя версия не теряется"
    # снятие отзыва
    assert client.delete(f"{url}/{ref1}", headers=H(te)).status_code == 204
    assert client.delete(f"{url}/{ref1}", headers=H(te)).status_code == 404
    # «ещё похожих на этого» — новой версией от v2
    r = client.post(f"/api/employer/needs/{nid}/selections/2/similar", headers=H(te), json={"ref": ref1})
    assert r.status_code == 201, r.text
    v3 = r.json()
    assert v3["version"] == 3 and v3["parent_version"] == 2 and v3["filters"]["origin"]["ref"] == ref1
    assert v3["filters"]["categories"] == ["backend.middle"] and ref2 not in [x["ref"] for x in v3["results"]]
    assert client.post(f"/api/employer/needs/{nid}/selections/2/similar", headers=H(te),
                       json={"ref": ref2}).status_code == 404  # исключённого в v2 нет


# ------------------------------------------------------------------ Н3: ссылка руководителю

def test_share_link_public_no_pii_reactions_revoke_expiry(client):
    from app.modules.mutual.models import SelectionShare

    w = _world(client)
    te, nid, ref1 = w["te"], w["need"]["id"], w["refs"][0]
    r = client.post(f"/api/employer/needs/{nid}/shares", headers=H(te), json={"label": "Руководитель платежей"})
    assert r.status_code == 201, r.text
    sh = r.json()
    token = sh["token"]
    assert sh["path"] == f"/share/{token}" and sh["status"] == "active" and sh["version"] == 1
    days = (sh["expires_at"][:10], (utcnow() + timedelta(days=7)).date().isoformat())
    assert days[0] == days[1]
    pub = client.get(f"/api/share/{token}")  # без входа
    assert pub.status_code == 200, pub.text
    body = pub.json()
    assert body["need_title"] and {c["ref"] for c in body["candidates"]} >= set(w["refs"])
    assert all(c["fit"]["level"] for c in body["candidates"] if c["ref"] in w["refs"])
    for s in ("Иван", "Петров", "+7 900", "c1@example.com", "hr@corp.ru", *SECRET_MINIMA, "raw_text"):
        assert s not in pub.text, s
    r = client.post(f"/api/share/{token}/reactions", json={"ref": ref1, "verdict": "interesting",
                                                           "comment": "Зовём на техинтервью", "author": "Олег"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/share/{token}/reactions", json={"ref": ref1, "verdict": "no", "comment": "Передумал"})
    assert r.status_code == 200 and r.json()["verdict"] == "no"
    assert client.post(f"/api/share/{token}/reactions", json={"ref": "K-NOPE00", "verdict": "no"}).status_code == 404
    assert client.get(f"/api/share/{token}").json()["reactions"][ref1]["comment"] == "Передумал"
    # рекрутер видит отметку и в подборке, и в списке ссылок; токен в списке не возвращается
    m = _mutual(client, w)
    assert m["reactions"][ref1][0]["verdict"] == "no" and m["reactions"][ref1][0]["share_label"] == "Руководитель платежей"
    lst = client.get(f"/api/employer/needs/{nid}/shares", headers=H(te))
    assert lst.status_code == 200 and lst.json()[0]["views"] == 2 and token not in lst.text
    assert lst.json()[0]["reactions"][0]["ref"] == ref1
    # отзыв ссылки
    r = client.post(f"/api/employer/needs/{nid}/shares/{sh['id']}/revoke", headers=H(te))
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    g = client.get(f"/api/share/{token}")
    assert g.status_code == 410 and g.json()["detail"]["code"] == "share_revoked"
    assert client.post(f"/api/share/{token}/reactions", json={"ref": ref1, "verdict": "no"}).status_code == 410
    # истечение 7 дней
    t2 = client.post(f"/api/employer/needs/{nid}/shares", headers=H(te), json={}).json()["token"]
    with SessionLocal() as db:
        db.execute(update(SelectionShare).where(SelectionShare.revoked_at.is_(None))
                   .values(expires_at=utcnow() - timedelta(minutes=1)))
        db.commit()
    g = client.get(f"/api/share/{t2}")
    assert g.status_code == 410 and g.json()["detail"]["code"] == "share_expired"
    assert client.get("/api/share/" + "x" * 32).status_code == 404
    assert client.get("/api/share/short").status_code == 404
    # хранится только хеш токена
    with SessionLocal() as db:
        assert all(s.token_hash != token and len(s.token_hash) == 64 for s in db.scalars(select(SelectionShare)))


def test_share_hides_candidate_who_closed_profile(client):
    from app.modules.profiles.models import CandidateProfile

    w = _world(client)
    sh = client.post(f"/api/employer/needs/{w['need']['id']}/shares", headers=H(w["te"]), json={}).json()
    with SessionLocal() as db:
        db.execute(update(CandidateProfile).where(CandidateProfile.public_ref == w["refs"][0])
                   .values(visible_to_employers=False))
        db.commit()
    body = client.get(f"/api/share/{sh['token']}").json()
    assert w["refs"][0] not in [c["ref"] for c in body["candidates"]] and body["hidden"] >= 1


# ------------------------------------------------------------------ права

def test_access_rules(client):
    w = _world(client)
    nid, ref1 = w["need"]["id"], w["refs"][0]
    other = employer(client, "hr2@other.ru", "ООО Другая")
    tc = w["t"][0]
    sh = client.post(f"/api/employer/needs/{nid}/shares", headers=H(w["te"]), json={}).json()
    routes = [("get", f"/api/employer/needs/{nid}/selections/1/mutual", None),
              ("put", f"/api/employer/needs/{nid}/feedback", {"ref": ref1, "version": 1, "verdict": "fit"}),
              ("post", f"/api/employer/needs/{nid}/selections/1/refine", None),
              ("post", f"/api/employer/needs/{nid}/selections/1/similar", {"ref": ref1}),
              ("post", f"/api/employer/needs/{nid}/shares", {}),
              ("get", f"/api/employer/needs/{nid}/shares", None),
              ("post", f"/api/employer/needs/{nid}/shares/{sh['id']}/revoke", None)]
    for method, url, body in routes:
        kw = {"json": body} if body is not None else {}
        assert getattr(client, method)(url, **kw).status_code == 401, url
        assert getattr(client, method)(url, headers=H(tc), **kw).status_code == 403, url
        assert getattr(client, method)(url, headers=H(other), **kw).status_code == 404, url
    assert client.get(f"/api/share/{sh['token']}").status_code == 200, "чужой отзыв ссылки не сработал"
    r = client.post("/api/employer/mutual/offer-check", json={"candidate_ref": ref1, "salary_to": 1})
    assert r.status_code == 401
    r = client.post("/api/employer/mutual/offer-check", headers=H(other),
                    json={"candidate_ref": ref1, "need_id": nid, "salary_to": 100000})
    assert r.status_code == 404, "чужая потребность в подсказке"
    assert client.get("/api/candidate/preferences").status_code == 401
    assert client.get("/api/candidate/preferences", headers=H(w["te"])).status_code == 403


# ------------------------------------------------------------------ кандидат: интересы и «почему меня выбрали»

def test_candidate_preferences_and_why(client):
    w = _world(client)
    t1, ref1, te, nid = w["t"][0], w["refs"][0], w["te"], w["need"]["id"]
    g = client.get("/api/candidate/preferences", headers=H(t1)).json()
    assert g["preferences"] is None and "python" in g["survey_stack"] and "payments" in g["options"]["tasks"]
    assert client.put("/api/candidate/preferences", headers=H(t1), json={"interest_tags": ["cobol-9000"]}).status_code == 422
    assert client.put("/api/candidate/preferences", headers=H(t1), json={"interest_tasks": ["space"]}).status_code == 422
    r = client.put("/api/candidate/preferences", headers=H(t1), json={
        "offers_status": "active", "interest_tags": ["python", "fastapi"], "interest_tasks": ["payments"]})
    assert r.status_code == 200 and r.json()["preferences"]["offers_status"] == "active"
    m = _mutual(client, w)["items"][ref1]
    by = {f["key"]: f for f in m["factors"]}
    assert by["tasks"]["status"] == "ok" and "платёж" in by["tasks"]["text"].lower()
    assert by["readiness"]["text"] == "Ищет работу активно" and "интересах кандидата" in by["stack"]["text"]
    inv = client.post("/api/employer/invitations", headers=H(te),
                      json={**INVITE, "candidate_ref": ref1, "need_id": nid, "salary_from": 200000, "salary_to": 240000})
    assert inv.status_code == 201, inv.text
    iid = inv.json()["id"]
    why = client.get(f"/api/candidate/invitations/{iid}/why", headers=H(t1))
    assert why.status_code == 200, why.text
    y = why.json()
    assert y["need"]["title"] and y["place"]["version"] == 1 and 1 <= y["place"]["rank"] <= y["place"]["total"]
    assert any(x["requirement"] == "Обязательно: Python" for x in y["matched"])
    assert y["counts"]["confirmed"] + y["counts"]["declared"] + y["counts"]["missing"] >= 2
    sal = {f["key"]: f for f in y["offer"]["factors"]}["salary"]
    assert sal["status"] == "bad" and "ниже вашего минимума" in sal["text"]
    # чужое приглашение — 404
    other = w["t"][1]
    assert client.get(f"/api/candidate/invitations/{iid}/why", headers=H(other)).status_code == 404
    assert client.get(f"/api/candidate/invitations/{iid}/why", headers=H(te)).status_code == 403


def test_preferences_saved_before_category(client):
    """Интересы можно указать сразу после регистрации — до опроса и теста."""
    from app.modules.mutual.models import CandidatePreference

    t = register_and_verify(client, email="solo@example.com")
    assert client.put("/api/candidate/preferences", headers=H(t), json={"offers_status": "open"}).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(CandidatePreference)) is not None


# ------------------------------------------------------------------ песочница жюри

def test_jury_sandbox_has_mutual_demo(client):
    from app.modules.jury import scope

    r = client.post("/api/jury/login", json={"persona": "employer", "scenario": "new"})
    assert r.status_code == 200, r.text
    te = r.json()["access_token"]
    sid = scope.parse(client.get("/api/me", headers=H(te)).json()["email"])[1]
    needs = client.get("/api/employer/needs", headers=H(te)).json()
    need = next(n for n in needs if n["title"].startswith("Backend"))
    m = client.get(f"/api/employer/needs/{need['id']}/selections/1/mutual", headers=H(te)).json()
    tm = client.post("/api/jury/login", json={"persona": "candidate", "scenario": sid}).json()["access_token"]
    maria = my_ref(client, tm)
    assert m["feedback"][maria]["verdict"] == "fit" and m["reactions"][maria][0]["verdict"] == "interesting"
    assert m["items"][maria]["level"] == "high", m["items"][maria]
    assert any(f["verdict"] == "unfit" for f in m["feedback"].values())
    shares = client.get(f"/api/employer/needs/{need['id']}/shares", headers=H(te)).json()
    assert shares and shares[0]["status"] == "active" and len(shares[0]["reactions"]) >= 2
    assert client.get("/api/candidate/preferences", headers=H(tm)).json()["preferences"]["offers_status"] == "active"
    # Илья видит, почему его выбрали: место в подборке v1 и требования потребности
    ti = client.post("/api/jury/login", json={"persona": "candidate_nofsp", "scenario": sid}).json()["access_token"]
    inv = client.get("/api/candidate/invitations", headers=H(ti)).json()
    inv = inv[0] if isinstance(inv, list) else inv["items"][0]
    y = client.get(f"/api/candidate/invitations/{inv['id']}/why", headers=H(ti)).json()
    assert y["place"]["version"] == 1 and y["matched"] and y["offer"]["level"] in fitm.LEVELS
    # другая песочница не видит ни потребность, ни ссылки
    to = client.post("/api/jury/login", json={"persona": "employer", "scenario": "new"}).json()["access_token"]
    assert client.get(f"/api/employer/needs/{need['id']}/shares", headers=H(to)).status_code == 404
