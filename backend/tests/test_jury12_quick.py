"""Я9 «Проверка за 12 минут»: GET /api/jury/quick — демо-кандидаты своей песочницы в подборке своей потребности
и приглашения им (чтобы эксперт пригласил персону, за которую потом войдёт и ответит). Чужая песочница и чужая
потребность не видны; не жюри — 403."""
from tests.conftest import register_and_verify
from tests.test_day2_rules import H, my_ref

NEED = ("Ищем Python-разработчика middle: FastAPI, PostgreSQL, Docker. Django не нужен, PHP не нужен. "
        "Желательно Redis. Удалённо, 200–260 тыс. ₽")
INVITE = {"position_title": "Python-разработчик (интеграции)", "contact_method": "Почта HR и звонок 20 минут",
          "offer_description": "Команда интеграций: FastAPI, PostgreSQL, Docker. Удалённо, гибкий график.",
          "salary_from": 200_000, "salary_to": 260_000}


def _login(client, persona: str, scenario: str) -> dict:
    r = client.post("/api/jury/login", json={"persona": persona, "scenario": scenario})
    assert r.status_code == 200, r.text
    return r.json()


def _need(client, tok: str) -> str:
    p = client.post("/api/employer/needs/parse", json={"text": NEED}, headers=H(tok)).json()
    assert [x["tag"] for x in p["excluded"]] == ["django", "php"]  # отрицание заготовки — в исключённых, с цитатой
    req = {k: p[k] for k in ("direction", "grade", "stack_required", "stack_desired", "experience_years_min",
                             "work_format", "work_formats", "city", "salary_from", "salary_to", "excluded")}
    r = client.post("/api/employer/needs", json={"text": p["text"], "requirements": req}, headers=H(tok))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_quick_personas_ranks_and_own_invitation(client):
    a = _login(client, "employer", "new")
    sid, emp = a["scenario"], a["access_token"]
    need = _need(client, emp)

    r = client.get(f"/api/jury/quick?need={need}", headers=H(emp))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["scenario"] == sid and d["need"]["id"] == need and d["need"]["total"] > 0 and d["need"]["version"] == 1
    by = {p["persona"]: p for p in d["personas"]}
    assert set(by) == {"candidate", "candidate_nofsp", "candidate_junior", "candidate_new"}
    assert by["candidate"]["name"] == "Мария Королёва" and by["candidate_nofsp"]["name"] == "Илья Сергеев"
    # ref — тот самый кандидат, за которого входит эксперт
    for p in ("candidate", "candidate_nofsp"):
        assert by[p]["ref"] == my_ref(client, _login(client, p, sid)["access_token"])
    # Backend · Middle по Python: Мария и Илья — в подборке; место совпадает с выдачей
    res = client.get(f"/api/employer/needs/{need}/selections/1", headers=H(emp)).json()["results"]
    place = {x["ref"]: x["rank"] for x in res}
    for p in ("candidate", "candidate_nofsp"):
        assert by[p]["rank"] == place[by[p]["ref"]]
    # Илье демо-работодатель уже писал (пригласить снова — через 30 дней); у кого приглашения компании нет — можно
    assert by["candidate_nofsp"]["can_invite"] is False and by["candidate_nofsp"]["invitation"]["status"] in ("sent", "viewed")
    free = [p for p in d["personas"] if p["can_invite"]]
    assert free and all(p["invitation"] is None or p["invitation"]["need_id"] != need for p in free)
    target = min(free, key=lambda p: p["rank"] or 10**6)

    r = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": target["ref"], "need_id": need},
                    headers=H(emp))
    assert r.status_code == 201, r.text
    # маршрут доступен любой персоне песочницы: проводник спрашивает его и после входа кандидатом
    cand = _login(client, target["persona"], sid)["access_token"]
    m = {p["persona"]: p for p in client.get(f"/api/jury/quick?need={need}", headers=H(cand)).json()["personas"]}
    assert m[target["persona"]]["invitation"]["need_id"] == need and m[target["persona"]]["invitation"]["status"] == "sent"
    assert m[target["persona"]]["can_invite"] is False

    # другая песочница: потребность A не видна, персоны — свои
    b = _login(client, "employer", "new")
    other = client.get(f"/api/jury/quick?need={need}", headers=H(b["access_token"])).json()
    assert other["need"] is None and all(p["rank"] is None for p in other["personas"])
    assert {p["ref"] for p in other["personas"]}.isdisjoint({p["ref"] for p in d["personas"]})


def test_quick_only_jury(client):
    assert client.get("/api/jury/quick").status_code == 401
    t = register_and_verify(client, email="hr@corp.ru", role="employer", company_name="ООО Ромашка")
    r = client.get("/api/jury/quick", headers=H(t))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "jury_only"
