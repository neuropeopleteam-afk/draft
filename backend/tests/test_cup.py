"""«Кубок работодателя»: участие только своей категории, псевдонимы в таблице, автопроверка без утечки ключей,
срок решения, оценка вслепую, итоги → приглашения с вилкой кубка (лимит 30 дней), запись в паспорт ФСП."""
from datetime import timedelta
import uuid

from sqlalchemy import select

from app.core.db import SessionLocal, utcnow
from tests.test_day2_rules import H, candidate_with_category, employer

CUP = {"title": "Надёжные платежи", "description": "Пять заданий банка на транзакции и идемпотентность.",
       "category_id": "backend.middle", "mode": "auto", "n_tasks": 5, "time_limit_min": 15, "duration_days": 7,
       "salary_from": 240000, "salary_to": 300000, "invite_top_n": 2, "min_score": 0.5,
       "position_title": "Backend-разработчик", "offer_description": "Платёжное ядро, команда 6 человек, удалённо.",
       "contact_method": "Telegram @hr_corp"}


def keys_of(cup_id: str, email: str) -> dict:
    from app.cup.models import CupEntry
    from app.modules.auth.models import User

    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        e = db.scalar(select(CupEntry).where(CupEntry.cup_id == uuid.UUID(cup_id), CupEntry.candidate_user_id == u.id))
        return {it["token"]: it["key"]["value"] for it in e.tasks}


def wrong(task: dict, key):
    if task["kind"] == "option":
        return next(o["id"] for o in task["options"] if o["id"] != key)
    if task["kind"] == "line":
        return int(key) % max(2, task["code_lines"]) + 1
    return "заведомо неверный вывод"


def play(client, t, email, cup_id, n_correct: int) -> dict:
    r = client.post(f"/api/candidate/cups/{cup_id}/start", headers=H(t))
    assert r.status_code == 200, r.text
    tasks = r.json()["my_entry"]["tasks"]
    assert tasks and all("key" not in x and "seed" not in x and "family_id" not in x for x in tasks)
    keys = keys_of(cup_id, email)
    ans = {x["token"]: (keys[x["token"]] if i < n_correct else wrong(x, keys[x["token"]])) for i, x in enumerate(tasks)}
    r = client.post(f"/api/candidate/cups/{cup_id}/submit", json={"answers": ans}, headers=H(t))
    assert r.status_code == 200, r.text
    return r.json()


def test_auto_cup_full_flow(client):
    te = employer(client)
    bad = client.post("/api/employer/cups", json={**CUP, "salary_from": 0}, headers=H(te))
    assert bad.status_code == 422  # вилка обязательна
    r = client.post("/api/employer/cups", json=CUP, headers=H(te))
    assert r.status_code == 201, r.text
    cup = r.json()
    assert cup["phase"] == "active" and cup["n_tasks"] == 5 and "task_families" not in cup
    a = candidate_with_category(client, "a@example.com")
    b = candidate_with_category(client, "b@example.com")
    c = candidate_with_category(client, "c@example.com")
    junior = candidate_with_category(client, "j@example.com", grade="junior")
    # другая категория кубок не видит и записаться не может
    assert client.get("/api/candidate/cups", headers=H(junior)).json()["items"] == []
    assert client.post(f"/api/candidate/cups/{cup['id']}/join", headers=H(junior)).status_code == 404
    lst = client.get("/api/candidate/cups", headers=H(a)).json()
    assert [x["id"] for x in lst["items"]] == [cup["id"]] and lst["items"][0]["below_my_minimum"] is False
    for t in (a, b, c):
        assert client.post(f"/api/candidate/cups/{cup['id']}/join", headers=H(t)).status_code == 200
    ra = play(client, a, "a@example.com", cup["id"], 5)
    assert ra["my_entry"]["score_pct"] == 100 and ra["my_entry"]["status"] == "scored"
    assert "correct" not in ra["my_entry"]["tasks"][0]  # верность раскрывается только после итогов
    play(client, b, "b@example.com", cup["id"], 1)
    # таблица результатов — только псевдонимы: ни имён, ни почт, ни номеров кандидатов
    board = client.get(f"/api/candidate/cups/{cup['id']}", headers=H(c)).json()["leaderboard"]
    flat = str(board)
    assert [x["alias"] for x in board][:2] == ["Участник 01", "Участник 02"]
    for secret in ("Иван", "Петров", "@example.com", "candidate_ref", "entry_id"):
        assert secret not in flat
    emp = client.get(f"/api/employer/cups/{cup['id']}", headers=H(te)).json()
    assert all("candidate_ref" not in x for x in emp["leaderboard"])  # до приглашения — без номеров
    # итоги до окончания — только явным «досрочно»
    assert client.post(f"/api/employer/cups/{cup['id']}/finish", json={}, headers=H(te)).status_code == 409
    r = client.post(f"/api/employer/cups/{cup['id']}/finish", json={"early": True}, headers=H(te))
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["phase"] == "finished" and res["summary"]["placed"] == 2 and res["summary"]["invited"] == 1
    top = res["leaderboard"][0]
    assert top["position"] == 1 and top["invited"] and top["candidate_ref"] and top["full_name"] is None
    low = res["leaderboard"][1]
    assert not low["invited"] and "порога" in low["invite_note"]
    # приглашение лучшему — с вилкой кубка и доказательством «место в кубке»
    inv = client.get("/api/candidate/invitations", headers=H(a)).json()
    assert len(inv) == 1 and inv[0]["salary_from"] == 240000 and inv[0]["salary_to"] == 300000
    assert "Кубок" in str(inv[0]["evidence"])
    assert client.get("/api/candidate/invitations", headers=H(b)).json() == []
    me = client.get(f"/api/candidate/cups/{cup['id']}", headers=H(a)).json()["my_entry"]
    assert me["place"] == 1 and me["invitation_status"] == "sent" and me["passport_status"] == "pending_link"
    assert all("correct" in x for x in me["tasks"])
    # после принятия работодатель видит имя в таблице
    assert client.post(f"/api/candidate/invitations/{inv[0]['id']}/accept", headers=H(a)).status_code == 200
    emp = client.get(f"/api/employer/cups/{cup['id']}", headers=H(te)).json()
    assert emp["leaderboard"][0]["full_name"] == "Иван Петров"
    # место в кубке — факт T1 в карточке (как зонд)
    card = client.get(f"/api/employer/candidates/{top['candidate_ref']}", headers=H(te)).json()
    assert any("Кубок" in p["title"] and p["verdict"] == "1 место из 2" for p in card["probes"])


def test_passport_entry_written_after_link(client):
    from app.core.enums import FspLinkSource
    from app.modules.auth.models import User
    from app.modules.fsp.models import FspAchievement, FspPassport

    te = employer(client)
    cup = client.post("/api/employer/cups", json={**CUP, "invite_top_n": 1}, headers=H(te)).json()
    a = candidate_with_category(client, "a@example.com")
    play(client, a, "a@example.com", cup["id"], 4)
    client.post(f"/api/employer/cups/{cup['id']}/finish", json={"early": True}, headers=H(te))
    assert client.get("/api/candidate/cups/passport", headers=H(a)).json()[0]["passport_status"] == "pending_link"
    with SessionLocal() as db:  # кандидат связал паспорт ФСП (ФСП ID / демо)
        u = db.scalar(select(User).where(User.email == "a@example.com"))
        db.add(FspPassport(user_id=u.id, link_source=list(FspLinkSource)[0]))
        db.commit()
    ev = client.get("/api/candidate/cups/passport", headers=H(a)).json()
    assert ev[0]["passport_status"] == "written" and ev[0]["place"] == 1 and ev[0]["event_level"] == "platform"
    with SessionLocal() as db:
        ach = db.scalars(select(FspAchievement)).all()
        assert len(ach) == 1 and ach[0].verified is False and ach[0].source_ref == f"cup:{cup['id']}"
        assert ach[0].event_level.value == "platform" and "победитель" in ach[0].result_title
    # повторная синхронизация не дублирует запись
    client.get("/api/candidate/cups", headers=H(a))
    with SessionLocal() as db:
        assert len(db.scalars(select(FspAchievement)).all()) == 1


def test_invitation_cooldown_respected(client):
    from tests.test_day2_rules import INVITE, my_ref

    te = employer(client)
    a = candidate_with_category(client, "a@example.com")
    r = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": my_ref(client, a)}, headers=H(te))
    assert r.status_code == 201, r.text
    cup = client.post("/api/employer/cups", json=CUP, headers=H(te)).json()
    play(client, a, "a@example.com", cup["id"], 5)
    res = client.post(f"/api/employer/cups/{cup['id']}/finish", json={"early": True}, headers=H(te)).json()
    assert res["summary"]["invited"] == 0 and "уже отправляла" in res["leaderboard"][0]["invite_note"]
    assert len(client.get("/api/candidate/invitations", headers=H(a)).json()) == 1


def test_deadline_and_grace(client):
    from app.cup.models import CupEntry

    te = employer(client)
    cup = client.post("/api/employer/cups", json=CUP, headers=H(te)).json()
    a = candidate_with_category(client, "a@example.com")
    r = client.post(f"/api/candidate/cups/{cup['id']}/start", headers=H(a)).json()
    with SessionLocal() as db:
        e = db.scalar(select(CupEntry))
        e.deadline_at = utcnow() - timedelta(minutes=5)  # срок + 2 минуты на сеть прошли
        db.commit()
    tok = r["my_entry"]["tasks"][0]["token"]
    r = client.post(f"/api/candidate/cups/{cup['id']}/submit", json={"answers": {tok: "A"}}, headers=H(a))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cup_time_over"
    assert client.get(f"/api/candidate/cups/{cup['id']}", headers=H(a)).json()["my_entry"]["status"] == "expired"
    assert client.post(f"/api/candidate/cups/{cup['id']}/start", headers=H(a)).status_code == 409


def test_employer_mode_blind_review(client):
    te = employer(client)
    cup = client.post("/api/employer/cups", json={**CUP, "mode": "employer", "invite_top_n": 1,
                                                  "task_text": "Опишите обработку повторных вебхуков без дублей."},
                      headers=H(te)).json()
    a = candidate_with_category(client, "a@example.com")
    pre = client.get(f"/api/candidate/cups/{cup['id']}", headers=H(a)).json()
    assert pre["my_entry"] is None and "task_text" not in pre  # задача — только после старта
    st = client.post(f"/api/candidate/cups/{cup['id']}/start", headers=H(a)).json()
    assert "вебхуков" in st["my_entry"]["task_text"]
    body = ("Храню event_id в таблице с уникальным индексом, обработка в одной транзакции. "
            "Мой телефон +7 900 111-22-33, почта a@example.com")
    r = client.post(f"/api/candidate/cups/{cup['id']}/submit",
                    json={"text": body, "link": "https://github.com/ivan-petrov/webhooks"}, headers=H(a))
    assert r.status_code == 200 and r.json()["my_entry"]["status"] == "submitted"
    emp = client.get(f"/api/employer/cups/{cup['id']}", headers=H(te)).json()
    sol = emp["solutions"][0]
    assert "111-22-33" not in sol["text"] and "a@example.com" not in sol["text"] and "event_id" in sol["text"]
    assert sol["has_link"] and "github" not in str(emp)  # ссылка может раскрыть личность — скрыта
    r = client.post(f"/api/employer/cups/{cup['id']}/finish", json={"early": True}, headers=H(te))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cup_unscored"
    r = client.post(f"/api/employer/cups/{cup['id']}/entries/{sol['entry_id']}/score", json={"score_pct": 80},
                    headers=H(te))
    assert r.status_code == 200 and r.json()["solutions"][0]["score_pct"] == 80
    r = client.post(f"/api/employer/cups/{cup['id']}/finish", json={"early": True}, headers=H(te))
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["invited"] == 1


def test_rubric_falls_back_to_employer_when_llm_off(client):
    te = employer(client)
    cup = client.post("/api/employer/cups", json={
        **CUP, "mode": "rubric", "task_text": "Спроектируйте обработку вебхуков без двойных списаний.",
        "rubric": [{"title": "Корректность решения", "weight": 0.6}, {"title": "Тесты и проверяемость", "weight": 0.4}]},
        headers=H(te)).json()
    assert [c["weight"] for c in cup["rubric"]] == [0.6, 0.4]
    a = candidate_with_category(client, "a@example.com")
    client.post(f"/api/candidate/cups/{cup['id']}/start", headers=H(a))
    r = client.post(f"/api/candidate/cups/{cup['id']}/submit",
                    json={"text": "Идемпотентность по ключу события, транзакция, тест на повтор."}, headers=H(a))
    assert r.json()["my_entry"]["status"] == "submitted"  # LLM выключен — оценит работодатель
    sol = client.get(f"/api/employer/cups/{cup['id']}", headers=H(te)).json()["solutions"][0]
    assert sol["llm"]["status"] == "pending"
    bad = client.post(f"/api/employer/cups/{cup['id']}/entries/{sol['entry_id']}/score",
                      json={"criteria": {"c1": 1}}, headers=H(te))
    assert bad.status_code == 422
    r = client.post(f"/api/employer/cups/{cup['id']}/entries/{sol['entry_id']}/score",
                    json={"criteria": {"c1": 1, "c2": 0.5}}, headers=H(te))
    assert r.json()["solutions"][0]["score_pct"] == 80


def test_roles_and_foreign_cups(client):
    te = employer(client)
    te2 = employer(client, email="hr2@corp.ru", company="ООО Лютик")
    a = candidate_with_category(client, "a@example.com")
    cup = client.post("/api/employer/cups", json=CUP, headers=H(te)).json()
    assert client.get("/api/employer/cups", headers=H(a)).status_code == 403
    assert client.get("/api/candidate/cups", headers=H(te)).status_code == 403
    assert client.get(f"/api/employer/cups/{cup['id']}", headers=H(te2)).status_code == 404
    assert client.post(f"/api/employer/cups/{cup['id']}/cancel", headers=H(te)).json()["status"] == "cancelled"
    assert client.get("/api/candidate/cups", headers=H(a)).json()["items"] == []


def test_options_and_validation(client):
    te = employer(client)
    o = client.get("/api/employer/cups/options", params={"category_id": "backend.middle"}, headers=H(te)).json()
    assert o["market"]["from"] > 0 and o["auto_tasks_available"] >= 3 and len(o["default_rubric"]) == 3
    r = client.post("/api/employer/cups", json={**CUP, "mode": "rubric", "task_text": ""}, headers=H(te))
    assert r.status_code == 422
    r = client.post("/api/employer/cups", json={**CUP, "salary_from": 400000}, headers=H(te))
    assert r.status_code == 422
