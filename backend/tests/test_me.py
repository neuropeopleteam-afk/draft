from tests.conftest import register_and_verify


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_me_requires_token(client):
    r = client.get("/api/me")
    assert r.status_code == 401
    assert client.get("/api/me", headers=auth("garbage")).status_code == 401


def test_candidate_me_has_neutral_fsp_state(client):
    token = register_and_verify(client, full_name="Анна Смирнова")
    me = client.get("/api/me", headers=auth(token)).json()
    assert me["role"] == "candidate"
    assert me["candidate"]["full_name"] == "Анна Смирнова"
    assert me["candidate"]["current_category_id"] is None  # категория только после теста
    assert me["fsp"] == {"linked": False, "link_source": None, "achievements_count": 0}
    assert me["employer"] is None


def test_candidate_updates_profile(client):
    token = register_and_verify(client)
    r = client.patch(
        "/api/me/candidate-profile",
        headers=auth(token),
        json={"city": "Москва", "work_format": "remote", "salary_min_hidden": 200000},
    )
    assert r.status_code == 200
    c = r.json()["candidate"]
    assert c["city"] == "Москва" and c["work_format"] == "remote" and c["salary_min_hidden"] == 200000


def test_employer_me_and_company_update(client):
    token = register_and_verify(client, email="hr@corp.ru", role="employer", company_name="ООО Ромашка")
    me = client.get("/api/me", headers=auth(token)).json()
    assert me["role"] == "employer" and me["employer"]["company"]["name"] == "ООО Ромашка"
    assert me["candidate"] is None
    r = client.patch("/api/me/company", headers=auth(token), json={"industry": "Финтех", "inn": "7701234567"})
    assert r.status_code == 200 and r.json()["employer"]["company"]["industry"] == "Финтех"


def test_role_separation(client):
    cand = register_and_verify(client)
    emp = register_and_verify(client, email="hr@corp.ru", role="employer")
    assert client.patch("/api/me/company", headers=auth(cand), json={"industry": "x"}).status_code == 403
    assert client.patch("/api/me/candidate-profile", headers=auth(emp), json={"city": "x"}).status_code == 403
