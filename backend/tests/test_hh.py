"""Я12: hh.ru — клиент на заглушке (заголовки, кэш, частота, ошибки), импорт своей вакансии в черновик, «Рынок по hh.ru»."""
from __future__ import annotations

import time

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.integrations.vacancies.models import Vacancy
from app.modules.hh import importer, market, stub
from app.modules.hh.client import HhClient, HhError
from tests.conftest import register_and_verify
from tests.test_day2_rules import H, employer

PREVIEW, IMPORT, MARKET = "/api/employer/vacancies/import/hh/preview", "/api/employer/vacancies/import/hh", "/api/employer/market/hh"
SECRET = "test-token-must-not-leak-0000"


@pytest.fixture
def hh_on(monkeypatch, tmp_path):
    monkeypatch.setenv("HH_ENABLED", "true")
    monkeypatch.setenv("HH_STUB", "true")
    monkeypatch.setenv("HH_CACHE_DIR", str(tmp_path / "hh"))
    get_settings.cache_clear()
    yield tmp_path / "hh"
    get_settings.cache_clear()


def _settings(tmp_path, **kw) -> Settings:
    return Settings(hh_enabled=True, hh_app_token=SECRET, hh_user_agent="platform-test/1.0 (test@example.com)",
                    hh_cache_dir=str(tmp_path / "c"), **kw)


# ------------------------------------------------------------------ ссылка или номер
@pytest.mark.parametrize("ref", ["90000001", " 90000001 ", "https://hh.ru/vacancy/90000001", "hh.ru/vacancy/90000001",
                                 "https://spb.hh.ru/vacancy/90000001?from=employer&hhtmFrom=x",
                                 "https://api.hh.ru/vacancies/90000001", "https://hh.ru/vacancy/90000001/"])
def test_parse_ref_accepts_link_or_number(ref):
    assert importer.parse_ref(ref) == "90000001"


@pytest.mark.parametrize("ref", ["", "abc", "https://example.com/vacancy/90000001", "https://hh.ru/resume/123456789",
                                 "12", "https://hh.ru/search/vacancy?text=python"])
def test_parse_ref_rejects_other(ref):
    with pytest.raises(HhError) as e:
        importer.parse_ref(ref)
    assert e.value.code == "hh_bad_ref" and e.value.status == 422


# ------------------------------------------------------------------ клиент
def test_client_headers_cache_and_no_token_in_errors(tmp_path):
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        if req.url.path == "/vacancies/404404":
            return httpx.Response(404, json={"errors": [{"type": "not_found"}]})
        if req.url.path == "/vacancies/403403":
            return httpx.Response(403, json={"errors": [{"type": "forbidden"}]})
        if req.url.path == "/vacancies/429429":
            return httpx.Response(429, json={"errors": [{"type": "too_many_requests"}]})
        return httpx.Response(200, json={"id": req.url.path.rsplit("/", 1)[-1]})

    cl = HhClient(_settings(tmp_path), transport=httpx.MockTransport(handler), min_interval_s=0)
    a = cl.get("/vacancies/1", ttl_s=60)
    b = cl.get("/vacancies/1", ttl_s=60)
    assert a["data"] == {"id": "1"} and not a["cached"] and b["cached"] and len(seen) == 1
    h = seen[0].headers
    assert h["authorization"] == f"Bearer {SECRET}"
    assert h["hh-user-agent"] == h["user-agent"] == "platform-test/1.0 (test@example.com)"
    for path, code, status in (("/vacancies/404404", "hh_not_found", 404), ("/vacancies/403403", "hh_forbidden", 502),
                               ("/vacancies/429429", "hh_rate_limited", 429)):
        with pytest.raises(HhError) as e:
            cl.get(path, ttl_s=60)
        assert (e.value.code, e.value.status) == (code, status) and SECRET not in e.value.message
    # токен не попадает в кэш на диске
    assert all(SECRET not in p.read_text() for p in (tmp_path / "c").rglob("*.json"))


def test_client_timeout_network_and_stale_cache(tmp_path):
    mode = {"fail": None}

    def handler(req):
        if mode["fail"] == "timeout":
            raise httpx.ReadTimeout("slow", request=req)
        if mode["fail"] == "net":
            raise httpx.ConnectError("down", request=req)
        if mode["fail"] == "500":
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"found": 1})

    cl = HhClient(_settings(tmp_path), transport=httpx.MockTransport(handler), min_interval_s=0)
    with pytest.raises(HhError) as e:
        mode["fail"] = "timeout"
        cl.get("/vacancies", {"text": "x"}, ttl_s=0)
    assert e.value.code == "hh_timeout" and "не ответил" in e.value.message
    with pytest.raises(HhError) as e:
        mode["fail"] = "net"
        cl.get("/vacancies", {"text": "x"}, ttl_s=0)
    assert e.value.code == "hh_unavailable"
    mode["fail"] = None
    ok = cl.get("/vacancies", {"text": "y"}, ttl_s=0)
    assert not ok["stale"]
    mode["fail"] = "500"  # срок кэша вышел (ttl 0), hh.ru не отвечает — честно отдаём прошлую запись с пометкой
    st = cl.get("/vacancies", {"text": "y"}, ttl_s=0)
    assert st["stale"] and st["cached"] and st["fetched_at"] == ok["fetched_at"]
    with pytest.raises(HhError):
        cl.get("/vacancies", {"text": "y"}, ttl_s=0, allow_stale=False)


def test_client_rate_limit_shared_between_clients(tmp_path):
    """Два клиента (как два воркера uvicorn) с одним каталогом кэша: между запросами не меньше интервала."""
    times = []

    def handler(req):
        times.append(time.monotonic())
        return httpx.Response(200, json={})

    s = _settings(tmp_path)
    a = HhClient(s, transport=httpx.MockTransport(handler), min_interval_s=0.3)
    b = HhClient(s, transport=httpx.MockTransport(handler), min_interval_s=0.3)
    for i, cl in enumerate((a, b, a)):
        cl.get("/vacancies", {"page": i}, ttl_s=0)
    gaps = [y - x for x, y in zip(times, times[1:])]
    assert len(times) == 3 and all(g >= 0.28 for g in gaps), gaps


def test_client_without_token_is_disabled(tmp_path):
    cl = HhClient(Settings(hh_enabled=True, hh_cache_dir=str(tmp_path)))
    with pytest.raises(HhError) as e:
        cl.get("/vacancies/1", ttl_s=60)
    assert e.value.code == "hh_disabled"
    assert not Settings(hh_enabled=True).hh_available and not Settings(hh_app_token="x", hh_user_agent="y").hh_available
    assert Settings(hh_enabled=True, hh_app_token="x", hh_user_agent="y").hh_available


# ------------------------------------------------------------------ маппинг вакансии
def test_map_fixture_vacancies():
    fx = stub.fixtures()
    with SessionLocal() as db:
        m = importer.map_vacancy(db, fx["90000001"])
        assert m.category_id == "backend.middle" and m.city == "Санкт-Петербург" and m.work_format == "hybrid"
        assert {"python", "django", "postgresql", "docker"} <= set(m.stack) and "redis" in m.stack
        assert m.salary_from_hh and (m.salary_from, m.salary_to, m.salary_basis) == (220000, 300000, "gross")
        assert "<p>" not in m.description and "Условия с hh.ru — опыт: от 3 до 6 лет · график: 5/2, 8 часов" in m.description
        assert m.key_skills[:2] == ["Python", "Django Framework"] and not m.notes

        q = importer.map_vacancy(db, fx["90000002"])  # только «от», на руки, офис, «опыт не требуется»
        assert q.category_id == "qa.junior" and q.work_format == "office" and q.city == "Москва"
        assert not q.salary_from_hh and q.salary_basis == "net" and 0 < q.salary_from <= q.salary_to <= q.salary_from * 1.5
        assert any("указана только «от» (от 90\u00a0000 ₽ на руки)" in n for n in q.notes)
        assert "Опыт не требуется" in q.description

        f = importer.map_vacancy(db, fx["90000003"])  # валюта — не рубли
        assert f.category_id == "frontend.senior" and f.work_format == "remote"
        assert any("не в рублях за месяц" in n and "USD" in n for n in f.notes)

        no_grade = importer.map_vacancy(db, {**fx["90000001"], "name": "Python-разработчик",
                                             "description": "<p>Python, Django, PostgreSQL — API сервиса.</p>"})
        assert no_grade.category_id == "backend.middle" and any("подсказка" in n for n in no_grade.notes)
        hourly = importer.map_vacancy(db, {**fx["90000001"], "salary_range": {"from": 1500, "to": 2000, "currency": "RUR",
                                                                                "gross": True, "mode": {"id": "HOUR"}}})
        assert not hourly.salary_from_hh and any("за час" in n for n in hourly.notes)


def test_same_company_names():
    assert importer.same_company("Северный платёж", "Демо жюри: Северный платёж")
    assert importer.same_company("ООО «Ромашка»", "Ромашка")
    assert importer.same_company("ПАО Сбербанк", "Сбербанк России")
    assert not importer.same_company("Другая компания (демо)", "Демо жюри: Северный платёж")
    assert importer.same_company(None, "Ромашка") is None


# ------------------------------------------------------------------ API
def test_api_hidden_without_flag(client):
    te = employer(client)
    assert client.get("/api/meta").json()["hh"] == {"enabled": False, "stub": False}
    for r in (client.get(PREVIEW, params={"ref": "90000001"}, headers=H(te)),
              client.post(IMPORT, json={"ref": "90000001"}, headers=H(te)),
              client.get(MARKET, params={"category_id": "backend.middle"}, headers=H(te))):
        assert r.status_code == 404 and r.json()["detail"]["code"] == "hh_disabled"


def test_import_own_vacancy_creates_draft_and_dedups(client, hh_on):
    te = employer(client, company="Северный платёж")
    assert client.get("/api/meta").json()["hh"] == {"enabled": True, "stub": True}
    p = client.get(PREVIEW, params={"ref": "https://spb.hh.ru/vacancy/90000001?from=share"}, headers=H(te))
    assert p.status_code == 200, p.text
    d = p.json()
    assert d["own_company"] is True and not d["confirm_required"] and d["state"] == "new" and d["stub"]
    assert d["category_id"] == "backend.middle" and d["salary_hh"].startswith("от 220\u00a0000 до 300\u00a0000 ₽ до вычета")
    r = client.post(IMPORT, json={"ref": "90000001"}, headers=H(te))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["result"] == "created" and out["imported_at"]
    mine = {v["id"]: v for v in client.get("/api/employer/vacancies", headers=H(te)).json()}
    v = mine[out["vacancy_id"]]
    assert v["status"] == "draft" and v["source"] == "hh" and v["source_title"] == "hh.ru"
    assert v["external_id"] == "90000001" and v["external_url"] == "https://hh.ru/vacancy/90000001"
    assert v["imported_at"] and v["edited_after_import"] is False and v["salary_basis"] == "gross"
    # черновик не виден кандидатам (это не витрина)
    tc = register_and_verify(client, email="c1@example.com")
    assert all(x["id"] != out["vacancy_id"] for x in client.get("/api/vacancies", headers=H(tc)).json()["items"])
    # повтор — без дубля
    again = client.post(IMPORT, json={"ref": "hh.ru/vacancy/90000001"}, headers=H(te)).json()
    assert again["result"] == "skipped" and again["state"] == "same" and again["vacancy_id"] == out["vacancy_id"]
    # работодатель поправил черновик — повторный импорт не перетирает
    time.sleep(0.01)
    assert client.patch(f"/api/employer/vacancies/{out['vacancy_id']}", json={"title": "Python-разработчик (свой)"},
                        headers=H(te)).status_code == 200
    ed = client.post(IMPORT, json={"ref": "90000001"}, headers=H(te)).json()
    assert ed["result"] == "skipped" and ed["state"] == "edited"
    with SessionLocal() as db:
        assert db.query(Vacancy).filter(Vacancy.source == "hh").count() == 1


def test_import_foreign_vacancy_needs_confirmation(client, hh_on):
    te = employer(client, company="Северный платёж")
    d = client.get(PREVIEW, params={"ref": "90000003"}, headers=H(te)).json()
    assert d["own_company"] is False and d["confirm_required"] and "Импортируйте только вакансии своей компании" in d["notes"][0]
    r = client.post(IMPORT, json={"ref": "90000003"}, headers=H(te))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "hh_confirm_own"
    ok = client.post(IMPORT, json={"ref": "90000003", "confirm_own": True}, headers=H(te))
    assert ok.status_code == 200 and ok.json()["result"] == "created"


def test_import_errors_are_clear(client, hh_on):
    te = employer(client, company="Северный платёж")
    nf = client.get(PREVIEW, params={"ref": "90000999"}, headers=H(te))
    assert nf.status_code == 404 and nf.json()["detail"]["code"] == "hh_not_found"
    bad = client.get(PREVIEW, params={"ref": "https://example.com/x"}, headers=H(te))
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "hh_bad_ref"
    lim = client.post(IMPORT, json={"ref": "90000429"}, headers=H(te))
    assert lim.status_code == 429 and "повторите" in lim.json()["detail"]["message"]
    tc = register_and_verify(client, email="c2@example.com")
    assert client.get(PREVIEW, params={"ref": "90000001"}, headers=H(tc)).status_code == 403


# ------------------------------------------------------------------ рынок
def test_market_median_and_honest_labels(client, hh_on):
    te = employer(client, company="Северный платёж")
    r = client.get(MARKET, params={"category_id": "backend.middle", "city": "Москва"}, headers=H(te))
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["available"] and m["shown"] and not m["few_data"] and m["n"] >= market.MIN_OK and m["stub"]
    assert m["area"] == {"id": "1", "name": "Москва"} and not m["area_fallback"] and m["grade_by"] == "name"
    assert m["p25"] <= m["median"] <= m["p75"] and m["basis"] == "net" and m["median_gross"] > m["median"]
    assert m["as_of"] and 0 <= m["gross_share"] <= 1 and m["excluded"]["currency"] >= 0
    assert "не фактические зарплаты" in m["note"] and m["search_url"].startswith("https://hh.ru/search/vacancy?")
    assert "items" not in m  # агрегат, не витрина вакансий
    again = client.get(MARKET, params={"category_id": "backend.middle", "city": "Москва"}, headers=H(te)).json()
    assert again["cached"] and again["median"] == m["median"]
    # Казань: вакансий мало → вся Россия (с пометкой); удалённая работа — сразу Россия
    kz = client.get(MARKET, params={"category_id": "qa.senior", "city": "Казань"}, headers=H(te)).json()
    assert kz["area_fallback"] and kz["area"]["id"] == "113" and "вакансий мало" in kz["note"]
    assert [t["area"] for t in kz["tried"]][:2] == ["Казань", "Казань"]
    # неизвестная категория — честно «не считается»
    no = client.get(MARKET, params={"category_id": "devops.middle"}, headers=H(te)).json()
    assert no["available"] is False and no["reason"]


def test_market_few_data_hides_numbers(hh_on):
    items = [{"salary_range": {"from": 100000 + i * 1000, "to": None, "currency": "RUR", "gross": False}} for i in range(5)]

    class Cl:
        def get(self, path, params=None, **kw):
            if path == "/suggests/areas":
                return {"data": {"items": []}}
            return {"data": {"items": items, "found": 5}, "fetched_at": "2026-10-10T10:00:00+00:00", "cached": False,
                    "stale": False, "stub": True}

    m = market.market("backend.junior", "Москва", cl=Cl())
    assert m["n"] == 5 and not m["shown"] and m["median"] is None and m["note"].startswith("Мало данных: 5 вакансий")


def test_market_values_rules():
    assert market._value({"salary_range": {"from": 100000, "to": 140000, "currency": "RUR", "gross": False}}) == (120000, "net")
    v, kind = market._value({"salary_range": {"from": 200000, "to": None, "currency": "RUR", "gross": True}})
    assert kind == "gross" and v < 200000  # до вычета → на руки
    assert market._value({"salary_range": {"from": 3000, "currency": "USD"}}) == (None, "currency")
    assert market._value({"salary_range": {"from": 500, "to": 700, "currency": "RUR", "mode": {"id": "HOUR"}}}) == (None, "mode")
    assert market._value({"salary": None}) == (None, "no_salary")


def test_market_context_from_need_and_candidate(client, hh_on):
    from tests.test_day2_rules import candidate_with_category, my_ref

    tc = candidate_with_category(client, grade="junior")
    te = employer(client, company="Северный платёж")
    m = client.get(MARKET, params={"ref": my_ref(client, tc)}, headers=H(te)).json()
    assert m["category_id"] == "backend.junior" and m["available"]
    # потребность: категория из разбора, формат «удалённо» → вся Россия
    need = client.post("/api/employer/needs", json={"text": "Ищем Middle Python-разработчика: Django, PostgreSQL. "
                                                            "Работа полностью удалённо."}, headers=H(te))
    assert need.status_code == 201, need.text
    nm = client.get(MARKET, params={"need_id": need.json()["id"]}, headers=H(te)).json()
    assert nm["category_id"] == "backend.middle" and nm["remote"] and nm["area"]["id"] == "113"
    # чужая потребность не раскрывает контекст
    te2 = employer(client, email="hr2@corp.ru", company="Другая")
    other = client.get(MARKET, params={"need_id": need.json()["id"]}, headers=H(te2)).json()
    assert other["available"] is False


def test_validation_hh_parse_endpoint(client):
    r = client.get("/api/validation/hh-parse")
    assert r.status_code == 200
    d = r.json()
    assert d.get("missing") or (d["n"] >= 150 and d["code_commit"])
