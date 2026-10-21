"""Тесты доработок трёх кабинетов (агент А2): карта регионов ФСП, протоколы ФСП, избирательное открытие контактов, встречное условие «Да, если…», признак is_synthetic и счётчик трёхсторонней связи."""
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.profiles.models import CandidateProfile
from tests.conftest import register_and_verify

PASSWORD = "Passw0rd!"
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


def test_fsp_protocols_graceful_degradation_on_permission_error(client, monkeypatch):
    """P0 (21.10): если файл индекса протоколов недоступен или вызывает PermissionError, /api/me/fsp и /search не падают с 500."""
    from app.modules.fsp import protocols as prot_mod

    tc = candidate_with_category(client, "c_perm_fsp@example.com")
    monkeypatch.setenv("FSP_PROTOCOLS_INDEX", "/nonexistent_dir_700/index.json")
    monkeypatch.setattr(prot_mod, "DEFAULT_PATHS", ("/nonexistent_dir_700/index.json",))

    def _raise_perm(_self):
        raise PermissionError("Permission denied")

    monkeypatch.setattr(prot_mod.Path, "is_file", _raise_perm)
    r_fsp = client.get("/api/me/fsp", headers=H(tc))
    assert r_fsp.status_code == 200, r_fsp.text
    d_fsp = r_fsp.json()
    assert d_fsp["protocols_available"] is False
    assert d_fsp["protocols_indexed"] == 0

    r_search = client.post("/api/me/fsp/protocols/search", json={"fio": "Иванов Иван"}, headers=H(tc))
    assert r_search.status_code == 200, r_search.text
    assert r_search.json()["available"] is False


def test_fsp_protocols_two_step_status_judges_filter_and_fsp_claims_queue(client, tmp_path, monkeypatch):
    """P0-1, P0-2 (21.10): судьи ВК/1К и справки исключены; привязка без ФСП ID ставит pending_fsp (0.5 веса);
    представитель ФСП подтверждает заявку в очереди -> verified (полный вес); строка карточки содержит ЕКП, ЕВСК и стр. PDF."""
    import json
    from app.core.enums import UserRole
    from app.core.security import hash_password
    from app.modules.auth.service import issue_token
    from app.modules.demo.seed import _user
    from app.modules.fsp import protocols as prot_mod

    idx_file = tmp_path / "index.json"
    idx_data = {
        "schema_version": "1.0",
        "stats": {"documents": 2, "total_records": 3},
        "sources": [
            {
                "doc_id": "kr_2025_prod",
                "title": "Кубок России по спортивному программированию 2025",
                "ekp_no": "2025120001001477",
                "pdf_url": "https://fsp-russia.ru/upload/iblock/kr2025.pdf",
            }
        ],
        "records": [
            {
                "key_hash": "ath_rec_001",
                "fio_norm": "соколов алексей игоревич",
                "fio_hash": prot_mod.fio_sha256("Соколов Алексей Игоревич"),
                "birth_date": "2003-05-12",
                "discipline": "программирование продуктовое",
                "event_title": "Кубок России по спортивному программированию 2025",
                "event_id": "kr_2025_prod",
                "ekp_no": "2025120001001477",
                "date": "2025-11-15",
                "place": 2,
                "rank": None,
                "evsk_rank": "КМС",
                "evsk_status": "fulfilled",
                "evsk_basis_short": "Приложение № 24 к приказу Минспорта № 450, стр. 187",
                "team": "Сборная Москвы",
                "region": "г. Москва",
                "pdf_url": "https://fsp-russia.ru/upload/iblock/kr2025.pdf",
                "page": 3,
                "person": True,
            },
            {
                "key_hash": "judge_rec_002",
                "fio_norm": "соколов алексей игоревич",
                "fio_hash": prot_mod.fio_sha256("Соколов Алексей Игоревич"),
                "discipline": "программирование продуктовое",
                "event_title": "Кубок России 2025",
                "ekp_no": "2025120001001477",
                "date": "2025-11-15",
                "place": None,
                "rank": "ВК",
                "region": "г. Москва",
                "pdf_url": "https://fsp-russia.ru/upload/iblock/kr2025.pdf",
                "page": 1,
            },
            {
                "key_hash": "judge_doc_003",
                "fio_norm": "соколов алексей игоревич",
                "fio_hash": prot_mod.fio_sha256("Соколов Алексей Игоревич"),
                "event_id": "kr_2025_sk_otbor",
                "event_title": "Справка о составе судейской коллегии Кубка России 2025",
                "date": "2025-10-01",
                "place": 1,
                "rank": None,
                "pdf_url": "https://fsp-russia.ru/upload/iblock/judges.pdf",
                "page": 2,
            },
        ],
    }
    idx_file.write_text(json.dumps(idx_data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("FSP_PROTOCOLS_INDEX", str(idx_file))
    prot_mod._CACHE["mtime"] = None

    tc = candidate_with_category(client, "sokolov_fsp@example.com")
    ref = my_ref(client, tc)
    te = employer(client)

    # 1. Поиск: судья (ВК) и справка о судейской коллегии отфильтрованы, найдена ровно 1 запись спортсмена в статусе pending_fsp
    rs = client.post("/api/me/fsp/protocols/search", json={"fio": "Соколов Алексей Игоревич"}, headers=H(tc))
    assert rs.status_code == 200, rs.text
    matches = rs.json()["matches"]
    assert len(matches) == 1
    m = matches[0]
    assert m["key_hash"] == "ath_rec_001"
    assert m["protocol_status"] == "pending_fsp"
    assert m["ekp_no"] == "2025120001001477"
    assert m["evsk_rank"] == "КМС"
    assert m["protocol_ref"] == {
        "doc_id": "kr_2025_prod",
        "ekp_no": "2025120001001477",
        "page": 3,
        "url": "https://fsp-russia.ru/upload/iblock/kr2025.pdf",
    }

    # 2. Привязка кандидатом без ФСП ID -> статус pending_fsp
    rc = client.post(
        "/api/me/fsp/protocols/confirm",
        json={"key_hashes": ["ath_rec_001", "judge_rec_002"], "consent_employers": True},
        headers=H(tc),
    )
    assert rc.status_code == 200, rc.text
    assert rc.json()["added"] == 1
    assert rc.json()["pending_count"] == 1
    assert rc.json()["verified_count"] == 0

    # Проверяем карточку кандидата у работодателя до подтверждения ФСП
    card_before = client.get(f"/api/employer/candidates/{ref}", headers=H(te)).json()
    ach_before = card_before["fsp"]["achievements"][0]
    assert ach_before["protocol_status"] == "pending_fsp"
    assert ach_before["verified"] is False
    assert "Кубок России 2025" in ach_before["text"]
    assert "продуктовое программирование" in ach_before["text"]
    assert "2 место" in ach_before["text"]
    assert "ЕКП № 2025120001001477" in ach_before["text"]
    assert "разряд по ЕВСК: КМС" in ach_before["text"]
    assert "стр. 3" in ach_before["text"]
    strength_pending = card_before["fsp"]["strength"]
    assert strength_pending > 0

    # 3. Представитель ФСП открывает очередь заявок и подтверждает достижение
    with SessionLocal() as db:
        u_fsp = _user(db, "fsp_verifier@example.com", UserRole.fsp_analyst, hash_password("pass12345"))
        db.commit()
        tfsp = issue_token(u_fsp).access_token

    rq = client.get("/api/fsp-cabinet/protocol-claims?status=pending_fsp", headers=H(tfsp))
    assert rq.status_code == 200, rq.text
    q_items = rq.json()["items"]
    claim = next(x for x in q_items if x["candidate_ref"] == ref)
    assert claim["protocol_status"] == "pending_fsp"
    assert claim["ekp_no"] == "2025120001001477"
    assert claim["evsk_rank"] == "КМС"

    rd = client.post(
        f"/api/fsp-cabinet/protocol-claims/{claim['id']}/decide",
        json={"action": "approve", "note": "Сверено со стр. 3 протокола Кубка России"},
        headers=H(tfsp),
    )
    assert rd.status_code == 200, rd.text
    assert rd.json()["protocol_status"] == "verified"

    # 4. Карточка работодателя после подтверждения ФСП: статус verified, сила паспорта удвоилась
    card_after = client.get(f"/api/employer/candidates/{ref}", headers=H(te)).json()
    ach_after = card_after["fsp"]["achievements"][0]
    assert ach_after["protocol_status"] == "verified"
    assert ach_after["verified"] is True
    assert card_after["fsp"]["has_protocol_verified"] is True
    assert card_after["fsp"]["strength"] > strength_pending


def test_fsp_cabinet_real_protocols_vs_hh_demand(client):
    """P0-3 (21.10): кабинет ФСП возвращает сверку реальных протоколов ФСП (от А8) и спроса hh.ru без ПДн и с пометкой «мало данных»."""
    ta = analyst_token(client)
    r = client.get("/api/fsp-cabinet/regions", headers=H(ta))
    assert r.status_code == 200, r.text
    rm = r.json()["real_protocols_vs_hh"]
    assert rm["summary"]["judges_excluded"] is True
    assert rm["summary"]["documents_count"] == 18
    # число результатов и спортсменов — из снимка индекса протоколов (v6: 2 908 / 2 232), а не константой
    import json, pathlib
    import app.modules.fsp as _fsp
    st = json.loads((pathlib.Path(_fsp.__file__).parent / "evsk_data" / "index_stats.json").read_text(encoding="utf-8"))
    assert rm["summary"]["athlete_results"] == st["results"]
    assert rm["summary"]["unique_athletes"] == st["athletes"]
    assert rm["summary"]["athletes_with_evsk_norm"] in (125, 130)
    assert rm["summary"]["hh_total_vacancies"] >= 7000
    assert len(rm["by_discipline"]) == 5
    assert len(rm["by_rank"]) == 5
    assert len(rm["by_region"]) >= 10
    assert any(reg["insufficient_data"] is True and "мало данных" in reg["status_label"] for reg in rm["by_region"])


def test_ats_keys_90_days_rotate_revoke_and_account_delete_ats_log(client):
    """P1-4, P1-6, P1-7 (21.10): слоты собеседования, ключи ATS 90 дней (перевыпуск и отзыв), удаление аккаунта закрывает контакты и пишет в ATS."""
    te = employer(client)
    tc = candidate_with_category(client, "c_del_ats@example.com")
    client.patch("/api/me/candidate-profile", json={"full_name": "Удаляемый Кандидат", "phone": "+79995554433"}, headers=H(tc))
    ref = my_ref(client, tc)

    # 1. Срок действия 90 дней, ротация и отзыв вебхука
    r_rot = client.put(
        "/api/employer/ats/settings",
        json={
            "auto_push": True,
            "huntflow": {"enabled": False},
            "webhook": {"enabled": True, "url": "https://example.com/hook", "rotate": True},
        },
        headers=H(te),
    )
    assert r_rot.status_code == 200, r_rot.text
    wh = r_rot.json()["webhook"]
    assert wh["secret_set"] is True
    assert wh["ttl_days"] == 90
    assert wh["secret_expires_at"] is not None

    r_rev = client.put(
        "/api/employer/ats/settings",
        json={
            "auto_push": True,
            "huntflow": {"enabled": False},
            "webhook": {"enabled": False, "url": "https://example.com/hook", "revoke": True},
        },
        headers=H(te),
    )
    assert r_rev.status_code == 200, r_rev.text
    assert r_rev.json()["webhook"]["secret_set"] is False
    assert r_rev.json()["webhook"]["secret_expires_at"] is None

    # 2. Приглашение со слотами собеседования (P1-4) -> принятие кандидатом -> удаление аккаунта (P1-7)
    slots = [
        {"starts_at": "2026-10-25T11:00:00", "duration_min": 60, "format": "video", "place": "https://example.com/meet1"},
        {"starts_at": "2026-10-26T15:00:00", "duration_min": 60, "format": "video", "place": "https://example.com/meet2"},
    ]
    r_inv = client.post(
        "/api/employer/invitations",
        json={**INVITE, "candidate_ref": ref, "proposed_slots": slots},
        headers=H(te),
    )
    assert r_inv.status_code == 201, r_inv.text
    inv_id = r_inv.json()["id"]
    assert len(r_inv.json()["proposed_slots"]) == 2

    r_acc = client.post(f"/api/candidate/invitations/{inv_id}/accept", json={"slot_index": 1}, headers=H(tc))
    assert r_acc.status_code == 200, r_acc.text
    assert r_acc.json()["hiring"]["stage"] == "interview"
    assert "26.10.2026" in r_acc.json()["hiring"]["line"]

    # Удаление учётной записи кандидата
    r_del = client.post("/api/me/data/delete", json={"confirm": "УДАЛИТЬ", "password": PASSWORD}, headers=H(tc))
    assert r_del.status_code == 200, r_del.text

    # Контакты у работодателя закрыты, а в журнале ATS записано событие contacts_revoked
    inv_emp = next(x for x in client.get("/api/employer/invitations", headers=H(te)).json() if x["id"] == inv_id)
    assert inv_emp["contacts"] is None
    assert inv_emp["contacts_revoked"] is True

    dels = client.get("/api/employer/ats/deliveries", headers=H(te)).json()
    rev_events = [d for d in dels if d.get("trigger") == "contacts_revoked" and d.get("invitation_id") == inv_id]
    assert len(rev_events) >= 1
    assert rev_events[0]["result"]["event"] == "candidate.contacts_revoked"


def test_company_response_speed_badge(client):
    """P1-5 (21.10): бейдж компании «Отвечает в среднем за N ч» скрыт при < 3 ответах и появляется при >= 3 реальных ответах."""
    from datetime import timedelta
    from app.core.db import utcnow
    from app.integrations.vacancies.models import Vacancy, VacancyApplication
    from app.modules.auth.models import User
    from app.modules.profiles.models import EmployerProfile

    te = employer(client)
    tc = candidate_with_category(client, "c_speed_badge@example.com")
    ref = my_ref(client, tc)

    # При 0 ответов бейдж скрыт (None)
    r_inv = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": ref}, headers=H(te))
    assert r_inv.status_code == 201
    invs_init = client.get("/api/candidate/invitations", headers=H(tc)).json()
    assert invs_init[0]["trust"].get("response_badge") is None

    # Добавляем 3 реальных отклика со временем реакции 2 ч, 4 ч, 6 ч (медиана = 4 ч)
    with SessionLocal() as db:
        emp_u = db.scalar(select(User).where(User.email == "hr@corp.ru"))
        ep = db.get(EmployerProfile, emp_u.id)
        cand_u = db.scalar(select(User).where(User.email == "c_speed_badge@example.com"))
        now = utcnow()
        for idx, hrs in enumerate((2, 4, 6)):
            v = Vacancy(
                company_id=ep.company_id,
                created_by=emp_u.id,
                title=f"Backend Developer #{idx}",
                description="Разработка серверных сервисов на Python и PostgreSQL.",
                category_id="backend.middle",
                salary_from=200000,
                salary_to=300000,
                status="published",
            )
            db.add(v)
            db.flush()
            db.add(
                VacancyApplication(
                    vacancy_id=v.id,
                    candidate_user_id=cand_u.id,
                    status="viewed",
                    created_at=now - timedelta(hours=10),
                    viewed_at=now - timedelta(hours=10 - hrs),
                )
            )
        db.commit()

    invs = client.get("/api/candidate/invitations", headers=H(tc)).json()
    badge = invs[0]["trust"]["response_badge"]
    assert badge is not None
    assert badge["median_hours"] == 4.0
    assert badge["sample_size"] == 3
    assert badge["label"] == "Отвечает в среднем за 4 ч"


def test_expert_checklist_7_salary_before_consent_contacts_hidden_and_revoke(client):
    """Чек-лист экспертов п. 7 (20.10): POST /api/employer/invitations без вилки → 422;
    кандидат видит компанию и вилку до согласия; контакты скрыты до согласия; отзыв контактов работает."""
    te = employer(client)
    tc = candidate_with_category(client, "c_expert7@example.com")
    client.patch(
        "/api/me/candidate-profile",
        json={"full_name": "Алексей Смирнов", "phone": "+79991112233", "telegram": "@alex_s"},
        headers=H(tc),
    )
    ref = my_ref(client, tc)

    # 1. Без вилки → 422
    no_sal = {k: v for k, v in INVITE.items() if k not in ("salary_from", "salary_to")}
    r_bad = client.post("/api/employer/invitations", json={**no_sal, "candidate_ref": ref}, headers=H(te))
    assert r_bad.status_code == 422

    # 2. До согласия контакты кандидата скрыты от работодателя
    card_before = client.get(f"/api/employer/candidates/{ref}", headers=H(te)).json()
    assert card_before["contacts"] is None

    # 3. Работодатель отправляет приглашение с вилкой; кандидат видит компанию и вилку до согласия
    r_inv = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": ref}, headers=H(te))
    assert r_inv.status_code == 201, r_inv.text
    inv_id = r_inv.json()["id"]
    assert r_inv.json()["contacts"] is None

    cand_invs = client.get("/api/candidate/invitations", headers=H(tc)).json()
    assert len(cand_invs) == 1
    assert cand_invs[0]["company"]["name"]
    assert cand_invs[0]["salary_from"] == INVITE["salary_from"]
    assert cand_invs[0]["salary_to"] == INVITE["salary_to"]

    # 4. После принятия контакты открываются, а после отзыва — снова закрыты
    r_acc = client.post(f"/api/candidate/invitations/{inv_id}/accept", json={}, headers=H(tc))
    assert r_acc.status_code == 200
    card_acc = client.get(f"/api/employer/candidates/{ref}", headers=H(te)).json()
    assert card_acc["contacts"] is not None
    assert card_acc["contacts"]["phone"] == "+79991112233"

    r_rev = client.post(f"/api/candidate/invitations/{inv_id}/contacts/revoke", headers=H(tc))
    assert r_rev.status_code == 200
    assert r_rev.json()["contacts_revoked"] is True
    card_rev = client.get(f"/api/employer/candidates/{ref}", headers=H(te)).json()
    assert card_rev["contacts"] is None
    assert card_rev["contacts_revoked"] is True


def test_index_v5_place_status_shared_range_and_unverified(client, tmp_path, monkeypatch):
    """index_v5 (21.10): поделённое место place_range [14, 24] при place=None -> «14–24 место»;
    evsk_status == place_unverified / place_status == not_recognized -> «место не подтверждено»."""
    import json
    from app.modules.fsp import protocols as prot_mod

    idx_file = tmp_path / "index_v5.json"
    idx_data = {
        "schema_version": "5.0",
        "stats": {"documents": 1, "total_records": 2},
        "sources": [
            {
                "doc_id": "chr_2025_alg",
                "title": "Чемпионат России по спортивному программированию 2025",
                "ekp_no": "2025120001001888",
                "pdf_url": "https://fsp-russia.ru/upload/iblock/chr2025.pdf",
            }
        ],
        "records": [
            {
                "key_hash": "v5_shared_14_24",
                "fio_norm": "морозов дмитрий сергеевич",
                "fio_hash": prot_mod.fio_sha256("Морозов Дмитрий Сергеевич"),
                "discipline": "программирование алгоритмическое",
                "event_title": "Чемпионат России по спортивному программированию 2025",
                "event_id": "chr_2025_alg",
                "ekp_no": "2025120001001888",
                "date": "2025-12-05",
                "place": None,
                "place_status": "shared_range",
                "place_range": [14, 24],
                "evsk_rank": "II разряд",
                "evsk_status": "fulfilled",
                "evsk_place_basis": 24,
                "evsk_basis_short": "п. 4 ЕВСК от 22.04.2025 (по худшему месту диапазона 24)",
                "region": "г. Санкт-Петербург",
                "pdf_url": "https://fsp-russia.ru/upload/iblock/chr2025.pdf",
                "page": 7,
                "person": True,
            },
            {
                "key_hash": "v5_unverified_01",
                "fio_norm": "морозов дмитрий сергеевич",
                "fio_hash": prot_mod.fio_sha256("Морозов Дмитрий Сергеевич"),
                "discipline": "программирование продуктовое",
                "event_title": "Кубок России по спортивному программированию 2025",
                "event_id": "kr_2025_prod",
                "ekp_no": "2025120001001477",
                "date": "2025-11-15",
                "place": None,
                "place_status": "not_recognized",
                "place_range": None,
                "evsk_rank": None,
                "evsk_status": "place_unverified",
                "region": "г. Санкт-Петербург",
                "pdf_url": "https://fsp-russia.ru/upload/iblock/kr2025.pdf",
                "page": 11,
                "person": True,
            },
        ],
    }
    idx_file.write_text(json.dumps(idx_data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("FSP_PROTOCOLS_INDEX", str(idx_file))
    prot_mod._CACHE["mtime"] = None

    tc = candidate_with_category(client, "c_v5_places@example.com")
    client.patch("/api/me/candidate-profile", json={"full_name": "Морозов Дмитрий Сергеевич"}, headers=H(tc))
    s_res = client.post("/api/me/fsp/protocols/search", json={}, headers=H(tc))
    assert s_res.status_code == 200
    matches = {m["key_hash"]: m for m in s_res.json()["matches"]}
    assert matches["v5_shared_14_24"]["place_display"] == "14–24 место"
    assert "14–24 место" in matches["v5_shared_14_24"]["formatted_text"]
    assert matches["v5_unverified_01"]["place_display"] == "место не подтверждено"
    assert "место не подтверждено" in matches["v5_unverified_01"]["formatted_text"]

    # Привязываем оба достижения и проверяем карточку работодателя + паспорт кандидата
    c_res = client.post(
        "/api/me/fsp/protocols/confirm",
        json={"key_hashes": ["v5_shared_14_24", "v5_unverified_01"], "consent_employers": True},
        headers=H(tc),
    )
    assert c_res.status_code == 200
    fsp_achs = c_res.json()["fsp"]["achievements"]
    texts = [a["text"] for a in fsp_achs]
    assert any("14–24 место" in t for t in texts), texts
    assert any("место не подтверждено" in t for t in texts), texts

    te = employer(client)
    ref = my_ref(client, tc)
    card_emp = client.get(f"/api/employer/candidates/{ref}", headers=H(te)).json()
    emp_texts = [a["text"] for a in card_emp["fsp"]["achievements"]]
    assert any("14–24 место" in t for t in emp_texts), emp_texts
    assert any("место не подтверждено" in t for t in emp_texts), emp_texts


def test_ats_webhook_no_contacts_before_consent_and_contacts_after_consent(client):
    """А2 (21.10): до согласия кандидата событие/карточка вебхука содержит только candidate_ref (consent=False, contacts=None);
    после принятия приглашения в вебхук ТОЛЬКО пригласившей компании уходят раскрытые кандидатом контакты
    (name/full_name, email, phone — с учётом shared_contacts), consent=True с временем согласия consent_at и валидной HMAC-подписью."""
    import uuid
    from app.core.db import SessionLocal
    from app.integrations.ats import clients as ats_clients
    from app.integrations.ats.service import export_payload
    from app.modules.invitations.models import Invitation
    from app.modules.profiles.models import Company

    orig_send = ats_clients._send
    ats_clients._send = lambda method, url, **kw: client.request(
        method, url.split("testserver", 1)[-1] if "testserver" in url else url, **kw
    )
    try:
        tc = candidate_with_category(client, "webhook_consent_cand@example.com")
        client.patch(
            "/api/me/candidate-profile",
            json={"full_name": "Соколова Анна Павловна", "phone": "+7 999 555-44-33", "telegram": "@anna_sokolova"},
            headers=H(tc),
        )
        ref = my_ref(client, tc)

        te1 = employer(client, "hr_inviter@corp1.ru", "1111111111")
        te2 = employer(client, "hr_other@corp2.ru", "2222222222")
        assert client.post("/api/employer/ats/stub/connect", headers=H(te1)).status_code == 200
        assert client.post("/api/employer/ats/stub/connect", headers=H(te2)).status_code == 200

        inv = client.post(
            "/api/employer/invitations",
            json={**INVITE, "candidate_ref": ref},
            headers=H(te1),
        ).json()

        # 1. До согласия кандидата: в ATS ничего не доставлено, а payload до согласия содержит ТОЛЬКО candidate_ref (без ПДн)
        assert client.get("/api/employer/ats/stub/records", headers=H(te1)).json() == []
        with SessionLocal() as db:
            inv_row = db.get(Invitation, uuid.UUID(inv["id"]))
            comp1 = db.get(Company, inv_row.company_id)
            pre = export_payload(db, comp1, invitation=inv_row)
        assert pre["candidate_ref"] == ref
        assert pre["consent"] is False
        assert pre["consent_at"] is None
        assert pre["contacts"] is None
        assert pre["candidate"]["contacts"] is None
        assert "Соколова" not in json.dumps(pre, ensure_ascii=False)
        assert "555-44-33" not in json.dumps(pre, ensure_ascii=False)
        assert "webhook_consent_cand@example.com" not in json.dumps(pre, ensure_ascii=False)

        # 2. Кандидат принимает приглашение и раскрывает имя, почту и телефон (без telegram)
        r_acc = client.post(
            f"/api/candidate/invitations/{inv['id']}/accept",
            json={"shared_contacts": ["full_name", "email", "phone"]},
            headers=H(tc),
        )
        assert r_acc.status_code == 200, r_acc.text

        # 3. В ATS пригласившей компании (te1) ушёл подписанный вебхук с контактами, consent=True и consent_at
        recs1 = client.get("/api/employer/ats/stub/records", headers=H(te1)).json()
        wh = next(r for r in recs1 if r["kind"] == "webhook")
        assert wh["signature_valid"] is True
        p = wh["payload"]
        assert p["event"] == "candidate.accepted_invitation"
        assert p["candidate_ref"] == ref
        assert p["consent"] is True
        assert isinstance(p["consent_at"], str) and len(p["consent_at"]) >= 19
        assert p["contacts"]["name"] == "Соколова Анна Павловна"
        assert p["contacts"]["full_name"] == "Соколова Анна Павловна"
        assert p["contacts"]["email"] == "webhook_consent_cand@example.com"
        assert p["contacts"]["phone"] == "+7 999 555-44-33"
        assert p["contacts"]["telegram"] is None  # кандидат не раскрывал telegram
        assert p["candidate"]["consent"] is True
        assert p["candidate"]["consent_at"] == p["consent_at"]
        assert p["candidate"]["contacts"]["phone"] == "+7 999 555-44-33"

        # 4. Вторая компания (te2), которая не приглашала / не получала согласия, вебхук и контакты НЕ получает
        recs2 = client.get("/api/employer/ats/stub/records", headers=H(te2)).json()
        assert recs2 == []
        with SessionLocal() as db:
            inv_row = db.get(Invitation, uuid.UUID(inv["id"]))
            comp2 = next(c for c in db.query(Company).all() if c.id != inv_row.company_id and c.inn == "2222222222")
            other_payload = export_payload(db, comp2, invitation=inv_row)
        assert other_payload["consent"] is False
        assert other_payload["contacts"] is None
        assert "Соколова" not in json.dumps(other_payload, ensure_ascii=False)
    finally:
        ats_clients._send = orig_send




