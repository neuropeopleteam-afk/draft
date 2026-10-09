"""Слияние волны 3 (Ф2 × песочница жюри): условия потребности применяются сразу, поэтому персоны песочницы
(удалённо, Москва) должны проходить условия всех своих демо-потребностей по backend — иначе жюри, войдя работодателем,
не увидит «своих» кандидатов в подборке (замечание Ф2 к слиянию)."""
from tests.test_day2_rules import H


def _login(client, persona, scenario=None):
    body = {"persona": persona, **({"scenario": scenario} if scenario else {})}
    r = client.post("/api/jury/login", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_jury_personas_pass_conditions_of_their_demo_needs(client):
    emp = _login(client, "employer", "new")
    tok = emp["access_token"]
    own = {c["ref"] for c in client.get("/api/employer/candidates", params={"direction": "backend"},
                                        headers=H(tok)).json()["items"]}
    assert len(own) == 4
    needs = client.get("/api/employer/needs", headers=H(tok)).json()
    backend_middle = [n for n in needs if n["requirements"].get("direction") == "backend"
                      and n["requirements"].get("grade") == "middle"]
    assert len(backend_middle) >= 2, [n["title"] for n in needs]
    for n in backend_middle:
        sel = client.get(f"/api/employer/needs/{n['id']}/selections/1", headers=H(tok)).json()
        refs = {c["ref"] for c in sel["results"]}
        # Мария и Илья (подтверждённый Middle) — в выдаче каждой backend-middle потребности песочницы,
        # ничего не скрыто условиями среди своих
        assert len(refs & own) >= 2, (n["title"], sel.get("conditions"), refs, own)
        cond = sel.get("conditions") or {}
        assert cond.get("applied"), (n["title"], cond)  # условия применены сразу (Ф2), не «любой формат»
    # потребность «интеграций»: условия — офис/гибрид в Москве или удалённо
    integ = next(n for n in backend_middle if "интеграций" in n["title"])
    req = integ["requirements"]
    assert set(req.get("work_formats") or []) >= {"office", "remote"} and req.get("city") == "Москва", req
