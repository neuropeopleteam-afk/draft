"""И23 п. 3: импорт вакансий из «Потока» — маппинг, дедупликация, права, понятное сообщение без токена, только чтение."""
from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.integrations.ats import clients
from app.integrations.ats.models import AtsConnection
from app.integrations.ats.providers import potok as pt
from app.integrations.vacancies import ats_import
from app.integrations.vacancies.models import Vacancy
from tests.conftest import register_and_verify
from tests.test_ats_providers import ats_http, http  # noqa: F401 — фикстуры
from tests.test_ats_stages import _pipeline, _sync, _move
from tests.test_day2_rules import H, candidate_with_category, employer

PREVIEW, IMPORT = "/api/employer/vacancies/import/potok/preview", "/api/employer/vacancies/import/potok"

# Как настоящий ответ GET /jobs.json (вакансия стенда 1714909, 09.10.2026): вилки нет, опыт «без опыта», город — id
# региона; author / jobs_users / executive_recruiter — ПДн рекрутёра, их платформа не читает и не хранит
REAL_JOB = {
    "id": 1714909, "name": "Backend-разработчик Python (Middle) — подбор через «Встречный»",
    "description": "<p>Требования: Python 3.12, FastAPI, PostgreSQL, SQL, Git, Docker. Тестовая вакансия для проверки "
                   "интеграции.</p><p>Обязанности:</p><p>Условия работы:</p>",
    "schedule_type": "fullDay", "salary_from": None, "salary_to": None, "experience_type": "noExperience",
    "employment_type": "full", "currency_type": "RUR", "key_skills": [], "city": "1", "archived": False,
    "state_id": "opened", "published": False, "applicants_count": {"all": 3, "active": 2},
    "stages": [{"id": 21101733, "name": "Добавлен", "serial": 2, "stage_type": "sourced"}],
    "author": {"id": 5, "name": "Рекрутёр Секретный", "email": "secret-recruiter@example.com"},
    "jobs_users": [{"user": {"name": "Рекрутёр Секретный", "email": "secret-recruiter@example.com",
                             "phone": "+7 999 000-00-00"}}],
    "executive_recruiter": {"name": "Рекрутёр Секретный"},
}


def _vacancies(client, te):
    return {v["external_id"]: v for v in client.get("/api/employer/vacancies", headers=H(te)).json()
            if v["source"] == "potok"}


def test_html_to_text_and_map_real_like_job():
    assert ats_import.html_to_text("<p>Раз&nbsp;два</p><ul><li>Python</li><li>SQL</li></ul><p></p>") == \
        "Раз два\nPython\nSQL"
    with SessionLocal() as db:
        m = ats_import.map_job(db, REAL_JOB)
        # грейд — из названия «(Middle)», а не из «без опыта»: стаж — только подсказка (VS.1)
        assert m.category_id == "backend.middle" and m.external_id == "1714909"
        assert {"python", "fastapi", "postgresql"} <= set(m.stack)
        assert m.city == "Москва" and m.work_format == "any" and not m.closed
        assert not m.salary_from_ats and 0 < m.salary_from <= m.salary_to <= m.salary_from * 1.5
        assert any("Вилка в «Потоке» не указана" in n for n in m.notes)
        assert "<p>" not in m.description and "Требования: Python 3.12" in m.description
        # без грейда в тексте опыт даёт только подсказку с пометкой
        hint = ats_import.map_job(db, {**REAL_JOB, "name": "Python-разработчик", "experience_type": "between3And6",
                                       "description": "<p>Python, FastAPI, PostgreSQL — API сервиса.</p>"})
        assert hint.category_id == "backend.middle" and any("подсказка" in n for n in hint.notes)
        closed = ats_import.map_job(db, {**REAL_JOB, "archived": True, "salary_from": 200000, "salary_to": 260000})
        assert closed.closed and closed.salary_from_ats and (closed.salary_from, closed.salary_to) == (200000, 260000)
        wide = ats_import.map_job(db, {**REAL_JOB, "salary_from": 100000, "salary_to": 300000})
        assert not wide.salary_from_ats and any("шире 1,5" in n for n in wide.notes)
    assert ats_import.job_url("https://app.potok.io/api/v3", 1714909) == "https://app.potok.io/j/1714909/"
    assert ats_import.job_url("http://stub/api/ats-stub/potok/api/v3", 1) is None


def test_rights_and_clear_message_without_token(client):
    assert client.get(PREVIEW).status_code == 401
    tc = register_and_verify(client, email="imp-cand@example.com")
    assert client.get(PREVIEW, headers=H(tc)).status_code == 403
    assert client.post(IMPORT, json={}, headers=H(tc)).status_code == 403
    te = employer(client)
    for r in (client.get(PREVIEW, headers=H(te)), client.post(IMPORT, json={}, headers=H(te))):
        assert r.status_code == 422, r.text
        assert "«Поток» не подключён" in r.json()["detail"]["message"] and "токен" in r.json()["detail"]["message"]


def test_demo_import_mapping_dedup_and_only_reads(client, ats_http, monkeypatch):  # noqa: F811
    te = employer(client)
    assert client.post("/api/employer/ats/providers/potok/demo", headers=H(te)).status_code == 200
    methods: list[tuple[str, str]] = []
    send = clients._send

    def spy(method, url, **kw):
        if "/potok/" in url:
            methods.append((method, url.split("/api/v3")[-1].split("?")[0]))
        return send(method, url, **kw)

    monkeypatch.setattr(clients, "_send", spy)
    p = client.get(PREVIEW, headers=H(te)).json()
    assert p["demo"] and p["total"] == 4 and {x["state"] for x in p["items"]} == {"new"}
    r = client.post(IMPORT, json={}, headers=H(te)).json()
    assert (r["created"], r["updated"], r["skipped"]) == (4, 0, 0)
    vs = _vacancies(client, te)
    pay, integ, front, arch = vs["410101"], vs["410102"], vs["410103"], vs["410104"]
    assert pay["source_title"] == "Поток" and pay["imported_at"] and pay["edited_after_import"] is False
    assert pay["status"] == "published" and pay["category_id"] == "backend.middle"
    assert (pay["salary_from"], pay["salary_to"]) == (240000, 280000) and pay["city"] == "Москва"
    assert {"python", "fastapi", "postgresql", "redis"} <= {s["tag"] for s in pay["stack"]}
    assert integ["category_id"] == "backend.junior" and integ["work_format"] == "remote"  # грейд — подсказка по опыту
    assert front["category_id"] == "frontend.middle" and front["city"] == "Санкт-Петербург"
    assert arch["status"] == "closed"
    # в «Потоке» — только чтение списка вакансий
    assert methods and all(m == "GET" and path == "/jobs.json" for m, path in methods), methods
    # дедупликация: повторный импорт ничего не создаёт
    again = client.post(IMPORT, json={}, headers=H(te)).json()
    assert (again["created"], again["updated"], again["skipped"]) == (0, 0, 4)
    with SessionLocal() as db:
        assert db.scalar(select(Vacancy).where(Vacancy.external_id == "410101").with_only_columns(
            Vacancy.id).limit(2)) is not None
        assert len(db.scalars(select(Vacancy).where(Vacancy.source == "potok")).all()) == 4
    # правка работодателем после импорта — повторный импорт её не перетирает
    assert client.patch(f"/api/employer/vacancies/{pay['id']}", json={"title": "Backend (платежи), своя редакция"},
                        headers=H(te)).status_code == 200
    st = {x["job_id"]: x["state"] for x in client.get(PREVIEW, headers=H(te)).json()["items"]}
    assert st[410101] == "edited" and st[410102] == "same"
    one = client.post(IMPORT, json={"job_ids": [410101]}, headers=H(te)).json()
    assert one["skipped"] == 1 and one["items"][0]["state"] == "edited"
    assert _vacancies(client, te)["410101"]["title"] == "Backend (платежи), своя редакция"


def test_application_to_imported_vacancy_goes_to_same_potok_job(client, ats_http):  # noqa: F811
    """Цикл «вакансия из «Потока» — отклик — этап»: отклик уходит в ту же вакансию «Потока», этап возвращается."""
    te = employer(client)
    tc = candidate_with_category(client)
    assert client.post("/api/employer/ats/providers/potok/demo", headers=H(te)).status_code == 200
    client.post(IMPORT, json={"job_ids": [410101]}, headers=H(te))
    v = _vacancies(client, te)["410101"]
    with SessionLocal() as db:
        conn = db.scalars(select(AtsConnection).where(AtsConnection.provider == "potok")).first()
        assert conn.vacancy_map[v["id"]]["id"] == 410101
    a = client.post(f"/api/vacancies/{v['id']}/apply", json={"consent_contacts": True}, headers=H(tc)).json()
    client.post(f"/api/employer/applications/{a['id']}/view", headers=H(te))
    r = client.post("/api/employer/ats/push", json={"application_id": a["id"]}, headers=H(te)).json()
    assert r[0]["status"] == "ok", r
    joins = _pipeline(client, te)
    assert [j["job_id"] for j in joins] == [410101]
    _sync(client, te)
    _move(client, te, joins[0]["join_id"], "interview_client")
    assert _sync(client, te)["changed"] == 1
    mine = client.get("/api/candidate/applications", headers=H(tc)).json()[0]
    assert mine["status"] == "accepted" and mine["ats_stage"]["stage"] == "interview"


def test_real_potok_mock_read_only_draft_without_salary_and_no_pii(client, http, monkeypatch):  # noqa: F811
    monkeypatch.setattr(pt, "check_url", lambda u: u)  # без DNS: адрес настоящего «Потока», ответы — мок
    te = employer(client)
    r = client.put("/api/employer/ats/providers/potok", json={"mode": "real", "token": "tok-real"}, headers=H(te))
    assert r.status_code == 200, r.text
    page = {"data": [REAL_JOB], "per_page": 100, "pages": 1, "page": 1}
    http.on("GET", r"app\.potok\.io/api/v3/jobs\.json$", (200, page), (200, page), (200, page))
    p = client.get(PREVIEW, headers=H(te)).json()
    assert not p["demo"] and p["items"][0]["url"] == "https://app.potok.io/j/1714909/"
    res = client.post(IMPORT, json={"job_ids": [1714909]}, headers=H(te)).json()
    assert res["created"] == 1 and "черновик" in res["items"][0]["text"]
    v = _vacancies(client, te)["1714909"]
    assert v["status"] == "draft" and v["external_url"] == "https://app.potok.io/j/1714909/"
    assert all(c["method"] == "GET" for c in http.calls)
    assert http.calls[0]["headers"]["Authorization"] == "Bearer tok-real"
    assert "secret-recruiter" not in str(v) and "Секретный" not in str(v)
    # повтор — без дубликата
    assert client.post(IMPORT, json={}, headers=H(te)).json()["created"] == 0
    # ошибка «Потока» (токен отозван) — понятный 502, вакансии не трогаем
    http.on("GET", r"jobs\.json$", (401, {"error": "unauthorized"}))
    bad = client.get(PREVIEW, headers=H(te))
    assert bad.status_code == 502 and "токен недействителен" in bad.json()["detail"]["message"]
