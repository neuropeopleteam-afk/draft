"""Тесты доработок трёх кабинетов (агент А2): карта регионов ФСП, протоколы ФСП, избирательное открытие контактов, встречное условие «Да, если…», признак is_synthetic и счётчик трёхсторонней связи."""
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.profiles.models import CandidateProfile
from tests.conftest import register_and_verify
from tests.test_day2_rules import INVITE, H, candidate_with_category, employer, my_ref
from tests.test_fsp_cabinet import analyst_token


def test_fsp_regions_map_and_report_integration(client):
    ta = analyst_token(client)
    res = client.get("/api/fsp-cabinet/regions", headers=H(ta))
    assert res.status_code == 200
    body = res.json()
    assert len(body["districts"]) == 8
    assert isinstance(body["recommendations"], list)
    assert "total_confirmed" in body
    assert "has_synthetic" in body

    rep = client.get("/api/fsp-cabinet/report", headers=H(ta)).json()
    assert "regions_map" in rep
    assert len(rep["regions_map"]["districts"]) == 8


def test_fsp_official_protocols_search_endpoint(client):
    tc = register_and_verify(client, email="fsp-proto@example.com")
    s = client.post(
        "/api/me/fsp/protocols/search",
        json={"fio": "Иванов Иван"},
        headers=H(tc),
    )
    assert s.status_code == 200
    data = s.json()
    assert "available" in data
    assert "matches" in data
    assert "count" in data


def test_is_synthetic_badge_and_selective_contacts_and_counter_offer(client):
    te = employer(client)
    tc_real = candidate_with_category(client, "real-cand@example.com")
    tc_syn = candidate_with_category(client, "syn-cand@example.com")
    ref_real = my_ref(client, tc_real)
    ref_syn = my_ref(client, tc_syn)

    with SessionLocal() as db:
        p_syn = db.scalar(select(CandidateProfile).where(CandidateProfile.public_ref == ref_syn))
        p_syn.is_synthetic = True
        p_real = db.scalar(select(CandidateProfile).where(CandidateProfile.public_ref == ref_real))
        p_real.phone = "+7 999 123-45-67"
        db.commit()

    all_cands = client.get("/api/employer/candidates", headers=H(te)).json()["items"]
    by_ref = {c["ref"]: c for c in all_cands}
    assert by_ref[ref_real]["is_synthetic"] is False
    assert by_ref[ref_syn]["is_synthetic"] is True

    # Приглашение и встречное условие «Да, если…» (с форматом и датой выхода)
    inv_res = client.post(
        "/api/employer/invitations",
        json={**INVITE, "candidate_ref": ref_real},
        headers=H(te),
    )
    assert inv_res.status_code == 201
    inv_id = inv_res.json()["id"]

    counter_res = client.post(
        f"/api/candidate/invitations/{inv_id}/counter",
        json={
            "salary_from": 260000,
            "salary_to": 320000,
            "work_format": "remote",
            "start_date": "через 2 недели",
            "comment": "Готов выйти при удалённом формате",
        },
        headers=H(tc_real),
    )
    assert counter_res.status_code == 201
    c_body = counter_res.json()
    assert c_body["counter"]["salary_from"] == 260000
    assert "удалён" in (c_body["counter"]["comment"] or "").lower()

    # Отклоняем встречное и проверяем выборочное принятие только с email
    dec = client.post(
        f"/api/employer/invitations/{inv_id}/counter/decline",
        json={"note": "Оставляем исходную вилку"},
        headers=H(te),
    )
    assert dec.status_code == 200

    acc = client.post(
        f"/api/candidate/invitations/{inv_id}/accept",
        json={"shared_contacts": ["email"]},
        headers=H(tc_real),
    )
    assert acc.status_code == 200
    assert acc.json()["shared_contacts"] == ["email"]

    emp_invs = client.get("/api/employer/invitations", headers=H(te)).json()
    target_inv = next(i for i in emp_invs if i["id"] == inv_id)
    assert target_inv["contacts"]["email"] == "real-cand@example.com"
    assert target_inv["contacts"]["phone"] is None

    # Отзыв согласия на публикацию в «Мои данные» немедленно закрывает контакты
    rev = client.delete("/api/me/consents/publication", headers=H(tc_real))
    assert rev.status_code == 200
    emp_invs_after = client.get("/api/employer/invitations", headers=H(te)).json()
    target_inv_after = next(i for i in emp_invs_after if i["id"] == inv_id)
    assert target_inv_after["contacts"] is None


def test_trio_unread_endpoint_roles(client):
    tc = register_and_verify(client, email="trio-c@example.com")
    te = employer(client)
    ta = analyst_token(client)
    for tok in (tc, te, ta):
        r = client.get("/api/trio/unread", headers=H(tok))
        assert r.status_code == 200
        body = r.json()
        assert "total" in body
        assert "pending_consent" in body
