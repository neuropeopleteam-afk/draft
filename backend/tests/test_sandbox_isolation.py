"""Изоляция песочниц жюри по прямым ссылкам (И15а, п. 3).

Списки (поиск, подборки, очередь эксперта) фильтруются через jury_scope.pool_clause, но объекты, доступные по
идентификатору, тоже обязаны подчиняться той же видимости: карточка и PDF кандидата по public_ref, сравнение,
зонды и приглашения по ref, вакансии и кубки песочницы. Правило: работодатель видит общий пул и свою песочницу,
чужая песочница для него не существует (404, как для скрытого профиля), — и наоборот, кандидат чужой песочницы не
видит её вакансий и кубков. Каждая проверка падала до исправления profile_by_ref / фильтра вакансий / create_cup.
Песочницы создаются долго (несколько секунд CPU каждая), поэтому проверки сгруппированы в два теста на одном «мире».
"""
import pytest

from tests.conftest import register_and_verify
from tests.test_day2_rules import H

VACANCY = {"title": "Backend-разработчик (песочница)", "category_id": "backend.middle",
           "description": "Вакансия демо-компании внутри песочницы жюри — видна только её кандидатам.",
           "stack": ["python"], "salary_from": 200_000, "salary_to": 260_000, "work_format": "remote", "publish": True}


def _jury(client, persona, scenario):
    r = client.post("/api/jury/login", json={"persona": persona, "scenario": scenario})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def world(client):
    """Две песочницы жюри (A и B), общее демо, настоящий работодатель; refs кандидатов песочницы A."""
    a = _jury(client, "employer", "new")
    b = _jury(client, "employer", "new")
    sid_a, sid_b = a["scenario"], b["scenario"]
    assert sid_a and sid_b and sid_a != sid_b
    shared = _jury(client, "employer", None)
    assert shared["shared"]
    real = register_and_verify(client, "hr@real-company.example.org", role="employer",
                               company_name="Настоящая компания")
    ea, eb, es = a["access_token"], b["access_token"], shared["access_token"]
    refs_a = [c["ref"] for c in client.get("/api/employer/candidates", params={"direction": "backend"},
                                           headers=H(ea)).json()["items"]]
    # после И1/И2 в выдаче песочницы 4 персоны-кандидата (Мария, Илья, «Junior (предварительно)», «Пройдите тест сами»)
    assert len(refs_a) == 4, refs_a
    return {"sid_a": sid_a, "sid_b": sid_b, "ea": ea, "eb": eb, "es": es, "er": real, "refs_a": refs_a,
            "ca": _jury(client, "candidate", sid_a)["access_token"],
            "cb": _jury(client, "candidate", sid_b)["access_token"]}


# ---------------------------------------------------------------- карточка, PDF, сравнение

def _card(client, world):
    ref = world["refs_a"][0]
    assert client.get(f"/api/employer/candidates/{ref}", headers=H(world["ea"])).status_code == 200
    for who in ("eb", "es", "er"):  # чужая песочница, общее демо, настоящий работодатель
        r = client.get(f"/api/employer/candidates/{ref}", headers=H(world[who]))
        assert r.status_code == 404, (who, r.status_code, r.text[:200])
        assert r.json()["detail"]["code"] == "candidate_not_found"
        assert "full_name" not in r.text and "theta" not in r.text


def _pdf(client, world):
    ref = world["refs_a"][1]
    ok = client.get(f"/api/employer/candidates/{ref}/profile.pdf", headers=H(world["ea"]))
    assert ok.status_code == 200 and ok.content[:4] == b"%PDF"
    for who in ("eb", "es", "er"):
        r = client.get(f"/api/employer/candidates/{ref}/profile.pdf", headers=H(world[who]))
        assert r.status_code == 404, (who, r.status_code)
        assert not r.content.startswith(b"%PDF")


def _compare(client, world):
    refs = world["refs_a"][:3]  # сравнение принимает 2–3 кандидатов
    need_b = client.get("/api/employer/needs", headers=H(world["eb"])).json()[0]["id"]
    r = client.get(f"/api/employer/needs/{need_b}/compare", params={"refs": refs}, headers=H(world["eb"]))
    assert r.status_code == 404, (r.status_code, r.text[:200])
    # в своей песочнице сравнение тех же кандидатов работает
    need_a = client.get("/api/employer/needs", headers=H(world["ea"])).json()[0]["id"]
    r = client.get(f"/api/employer/needs/{need_a}/compare", params={"refs": refs}, headers=H(world["ea"]))
    assert r.status_code == 200 and {c["ref"] for c in r.json()["candidates"]} == set(refs)


# ---------------------------------------------------------------- зонды и приглашения по ref

def _probe_and_invitation(client, world):
    ref = world["refs_a"][0]
    probe = {"candidate_refs": [ref], "title": "Зонд из чужой песочницы", "answer_mode": "any",
             "task_text": "Опишите, как бы вы спроектировали идемпотентный платёжный API на FastAPI.",
             "salary_from": 200_000, "salary_to": 250_000, "time_limit_min": 30}
    inv = {"candidate_ref": ref, "position_title": "Backend-разработчик", "contact_method": "Почта HR",
           "offer_description": "Команда платежей, FastAPI и PostgreSQL, удалённо, гибкий график работы.",
           "salary_from": 200_000, "salary_to": 250_000}
    for who in ("eb", "es", "er"):
        r = client.post("/api/employer/probes", json=probe, headers=H(world[who]))
        assert r.status_code == 404, (who, "probe", r.status_code, r.text[:200])
        r = client.post("/api/employer/invitations", json=inv, headers=H(world[who]))
        assert r.status_code == 404, (who, "invitation", r.status_code, r.text[:200])
    # кандидат песочницы A не получил ничего извне
    assert client.get("/api/candidate/probes", headers=H(world["ca"])).json() == []
    foreign = [i for i in client.get("/api/candidate/invitations", headers=H(world["ca"])).json()
               if i["position_title"] == "Backend-разработчик"]
    assert foreign == []
    # а своему работодателю — можно
    r = client.post("/api/employer/probes", json=probe, headers=H(world["ea"]))
    assert r.status_code == 201 and len(r.json()["created"]) == 1, r.text


# ---------------------------------------------------------------- вакансии песочницы

def _vacancies(client, world):
    r = client.post("/api/employer/vacancies", json=VACANCY, headers=H(world["ea"]))
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    real_c = register_and_verify(client, "dev@real.example.org")
    # своя песочница: видит, открывает, может откликнуться
    assert vid in {v["id"] for v in client.get("/api/vacancies", headers=H(world["ca"])).json()["items"]}
    assert client.get(f"/api/vacancies/{vid}", headers=H(world["ca"])).status_code == 200
    # чужая песочница и настоящий кандидат: вакансии не существует
    for who in ("cb", "er"):
        assert vid not in {v["id"] for v in client.get("/api/vacancies", headers=H(world[who])).json()["items"]}, who
        assert client.get(f"/api/vacancies/{vid}", headers=H(world[who])).status_code == 404, who
    assert vid not in {v["id"] for v in client.get("/api/vacancies", headers=H(real_c)).json()["items"]}
    assert client.get(f"/api/vacancies/{vid}", headers=H(real_c)).status_code == 404
    r = client.post(f"/api/vacancies/{vid}/apply", json={"consent_contacts": True}, headers=H(world["cb"]))
    assert r.status_code == 404, r.text
    r = client.post(f"/api/vacancies/{vid}/apply", json={"consent_contacts": True}, headers=H(real_c))
    assert r.status_code == 404, r.text
    # владелец видит свою вакансию и в ней нет чужих откликов
    assert client.get(f"/api/vacancies/{vid}", headers=H(world["ea"])).status_code == 200
    assert client.get(f"/api/employer/vacancies/{vid}/applications", headers=H(world["ea"])).json() == []
    # платформенные (не песочные) вакансии кандидат песочницы по-прежнему видит
    rv = register_and_verify(client, "hr2@real-company.example.org", role="employer", company_name="Открытая компания")
    pub = client.post("/api/employer/vacancies", json={**VACANCY, "title": "Открытая вакансия"},
                      headers=H(rv)).json()["id"]
    assert pub in {v["id"] for v in client.get("/api/vacancies", headers=H(world["ca"])).json()["items"]}
    assert client.get(f"/api/vacancies/{pub}", headers=H(world["cb"])).status_code == 200


# ---------------------------------------------------------------- кубки: засеянные (было) и созданные через API (дыра)

CUP = {"title": "Кубок песочницы", "description": "Кубок, созданный демо-работодателем песочницы жюри через API.",
       "mode": "auto", "n_tasks": 3, "time_limit_min": 15, "duration_days": 3, "salary_from": 200_000,
       "salary_to": 250_000, "position_title": "Backend-разработчик", "contact_method": "Почта HR",
       "offer_description": "Приглашение лучшим участникам кубка: команда платежей, удалённо, гибкий график."}


def _cup_hidden(client, cup_id, who):
    assert client.get(f"/api/candidate/cups/{cup_id}", headers=H(who)).status_code == 404
    assert client.post(f"/api/candidate/cups/{cup_id}/join", headers=H(who)).status_code == 404
    assert cup_id not in {c["id"] for c in client.get("/api/candidate/cups", headers=H(who)).json()["items"]}


def _cups(client, world):
    cups = client.get("/api/employer/cups", headers=H(world["ea"])).json()
    assert cups, "у демо-работодателя песочницы должны быть кубки"
    _cup_hidden(client, cups[0]["id"], world["cb"])  # засеянный кубок: изоляция была и раньше
    # кубок, созданный работодателем песочницы A через API: виден её кандидату, но не песочнице B и не настоящему
    cat = client.get("/api/me/card", headers=H(world["ca"])).json()["category"]["id"]
    r = client.post("/api/employer/cups", json={**CUP, "category_id": cat}, headers=H(world["ea"]))
    assert r.status_code == 201, r.text
    cup_id = r.json()["id"]
    assert client.get(f"/api/candidate/cups/{cup_id}", headers=H(world["ca"])).status_code == 200
    assert cup_id in {c["id"] for c in client.get("/api/candidate/cups", headers=H(world["ca"])).json()["items"]}
    _cup_hidden(client, cup_id, world["cb"])
    _cup_hidden(client, cup_id, register_and_verify(client, "dev2@real.example.org"))


def test_candidate_objects_by_ref_only_inside_own_sandbox(client, world):
    """Карточка, PDF, сравнение, зонд, приглашение по ref: чужая песочница, общее демо, настоящий работодатель — 404."""
    _card(client, world)
    _pdf(client, world)
    _compare(client, world)
    _probe_and_invitation(client, world)


def test_sandbox_vacancies_and_cups_are_isolated(client, world):
    """Вакансия песочницы видна только её кандидатам; кубок песочницы недоступен кандидату другой песочницы."""
    _vacancies(client, world)
    _cups(client, world)
