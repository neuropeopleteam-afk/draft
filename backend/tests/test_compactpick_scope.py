"""Я10: подборка по потребности вне каталога — «проверено тестом / НЕ проверено» и вопрос-зонд на непроверенный навык.

Порядок выдачи и баллы не меняются: scope считается только по требованиям версии и счётчику зондов по потребности.
"""
from app.modules.matching import coverage as cov_mod
from app.modules.matching.coverage import PROBES, ROLES, probe_for_skill, scope, bank_tags
from app.modules.matching.need_parser import parse_need
from tests.test_day2_rules import H, candidate_with_category, employer, my_ref

DEVOPS = "DevOps-инженер middle: Kubernetes, Terraform, Linux, Docker, CI/CD, мониторинг Prometheus. Удалённо, 200–260 тыс."
NORMAL = "Backend-разработчик middle: обязательно Python, FastAPI и PostgreSQL. Удалённо, 200–260 тыс."


def test_devops_scope_nearest_tested_and_not_tested():
    req = parse_need(DEVOPS, use_llm=False)
    sc = scope(req)
    assert sc and sc["out_of_catalog"] and sc["role"] == "devops" and sc["nearest_title"] == "Backend"
    tested = {x["title"] for x in sc["tested"]}
    untested = {x["title"]: x for x in sc["not_tested"]}
    assert {"Linux", "Docker"} <= tested                      # есть в заданиях теста Backend
    assert "Kubernetes" in untested and untested["Kubernetes"]["why"] == "нет заданий в тесте направления"
    assert untested["Terraform"]["why"] == "вне справочника"  # unknown_terms парсера
    assert not tested & set(untested)                         # навык не может быть сразу и там, и там
    assert sc["tested_note"] and sc["not_tested_note"]        # общий текст coverage для роли
    assert sc["probe"]["title"] == PROBES["devops"][0] and len(sc["probe"]["task"]) >= 20
    for x in sc["not_tested"]:                                # у каждого непроверенного — заготовка вопроса
        assert x["probe"]["title"].endswith(x["title"]) and len(x["probe"]["task"]) >= 20


def test_catalog_need_fully_covered_has_no_scope():
    assert scope(parse_need(NORMAL, use_llm=False)) is None
    assert scope(None) is None and scope({}) is None


def test_every_out_of_catalog_role_has_probe_template():
    assert {r[0] for r in ROLES} == set(PROBES)
    for title, task in PROBES.values():
        assert 3 <= len(title) <= 200 and len(task) >= 20     # ограничения формы зонда
    p = probe_for_skill("Kubernetes")
    assert p["title"] == "Вопрос по навыку: Kubernetes" and "Kubernetes" in p["task"]


def test_test_tags_follow_bank_direction():
    be, fe = bank_tags("backend"), bank_tags("frontend")
    assert "python" in be and "kubernetes" not in be
    assert be != fe and bank_tags(None) == cov_mod._bank_tags("")


def test_selection_version_has_scope_and_probe_counter(client):
    tc, te = candidate_with_category(client), employer(client)
    n = client.post("/api/employer/needs", json={"text": DEVOPS}, headers=H(te)).json()
    v1 = client.get(f"/api/employer/needs/{n['id']}/selections/1", headers=H(te)).json()
    sc = v1["scope"]
    assert sc["out_of_catalog"] and sc["probes"] == {"total": 0, "answered": 0, "reviewed": 0}
    order = [r["ref"] for r in v1["results"]]
    r = client.post("/api/employer/probes", json={
        "candidate_refs": [my_ref(client, tc)], "need_id": n["id"], "title": sc["probe"]["title"],
        "task_text": sc["probe"]["task"], "answer_mode": "any", "salary_from": 200_000, "salary_to": 260_000,
        "time_limit_min": 30}, headers=H(te))
    assert r.status_code == 201, r.text
    again = client.get(f"/api/employer/needs/{n['id']}/selections/1", headers=H(te)).json()
    assert again["scope"]["probes"]["total"] == 1
    assert [x["ref"] for x in again["results"]] == order      # порядок версии не меняется
    mine = client.get("/api/employer/probes", headers=H(te)).json()
    assert [p["need_id"] for p in mine] == [n["id"]]           # «зонды по этой потребности»: /employer/probes?need=
    plain = client.post("/api/employer/needs", json={"text": NORMAL}, headers=H(te)).json()
    assert client.get(f"/api/employer/needs/{plain['id']}/selections/1", headers=H(te)).json()["scope"] is None
