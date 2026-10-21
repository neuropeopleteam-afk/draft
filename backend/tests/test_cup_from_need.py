"""Н5: «Отборочный турнир ФСП под вакансию» — кубок компании × ФСП из потребности: 3 задания банка под обязательный
стек, приз с вилкой потребности для топ-5, паспорт соревновательной задачи, приглашение призёра в один клик, турнир
в «Кубке работодателя» и в Кабинете ФСП."""
import uuid

from sqlalchemy import select

from app.core.db import SessionLocal
from tests.test_cup import play
from tests.test_day2_rules import H, candidate_with_category, employer
from tests.test_employer_matching import NEED
from tests.test_fsp_cabinet import analyst_token


def _bank_families() -> int:
    """Размер банка — из самого банка: число семейств меняется вместе с банком (403 → 1504 на 20.10)."""
    from assessment_bank import load_specs

    n = len(load_specs())
    assert n >= 403  # банк не должен уменьшаться ниже прежнего объёма
    return n


def _need(client, te, text=NEED) -> dict:
    r = client.post("/api/employer/needs", json={"text": text}, headers=H(te))
    assert r.status_code == 201, r.text
    return r.json()


def test_pick_tasks_follow_required_stack():
    from assessment_bank import load_specs

    from app.cup import tasks as auto
    from app.cup.tournament import pick_tasks

    picked = pick_tasks("backend", "middle", ["python", "fastapi", "postgresql"], ["kafka"])
    assert pick_tasks("backend", "middle", ["python", "fastapi", "postgresql"], ["kafka"]) == picked  # детерминирован
    specs = load_specs()
    assert len(picked) == 3 and len({p["family_id"] for p in picked}) == 3
    assert len({p["format"] for p in picked}) == 3  # разные форматы
    for p in picked:
        s = specs[p["family_id"]]
        assert s.format in auto.AUTO_FORMATS and not s.canary and s.direction in ("backend", "common")
        assert not any(t in p["skills"] for t in ("Go", "Java"))  # технологии вне стека не выдаются
    assert all(p["matched"] for p in picked)  # каждое задание — по навыку стека потребности
    assert any(set(p["matched"]) & {"Python", "PostgreSQL", "SQL", "FastAPI"} for p in picked)


def test_tournament_from_need_flow(client):
    te = employer(client)
    need = _need(client, te)
    a = candidate_with_category(client, "a@example.com")
    b = candidate_with_category(client, "b@example.com")
    c = candidate_with_category(client, "c@example.com")

    r = client.post(f"/api/employer/cups/from-need/{need['id']}", headers=H(te))
    assert r.status_code == 201, r.text
    cup = r.json()
    t = cup["tournament"]
    assert cup["created"] is True and cup["mode"] == "auto" and cup["n_tasks"] == 3 and cup["invite_top_n"] == 5
    assert cup["category_id"] == "backend.middle" and cup["phase"] == "active"
    assert cup["salary_from"] == 220000 and cup["salary_to"] == 300000  # вилка — из потребности
    assert cup["position_title"] == need["title"] and "× ФСП" in cup["title"]
    assert t["discipline"] == "Продуктовое программирование" and t["need_id"] == need["id"]
    assert "Прямой оффер в компанию с подтверждённой вилкой из потребности" in t["prize"]
    assert "топ-5 призёров" in t["prize"] and "очки в рейтинг ФСП" in t["prize"]
    assert t["salary"]["source"] == "need" and len(t["tasks"]) == 3 and t["bank_size"] == _bank_families()
    assert {"Python", "FastAPI", "PostgreSQL"} <= set(t["stack"])
    assert all("key" not in x and "seed" not in x for x in t["tasks"])

    # повтор по той же потребности — тот же турнир, без дублей
    again = client.post(f"/api/employer/cups/from-need/{need['id']}", headers=H(te))
    assert again.status_code == 200 and again.json()["id"] == cup["id"] and again.json()["created"] is False
    mine = client.get("/api/employer/cups", headers=H(te)).json()
    assert [x["id"] for x in mine if x["tournament"]] == [cup["id"]]

    # кандидаты категории видят турнир и решают — у каждого свой вариант трёх заданий
    assert cup["id"] in [x["id"] for x in client.get("/api/candidate/cups", headers=H(a)).json()["items"]]
    for tok in (a, b, c):
        assert client.post(f"/api/candidate/cups/{cup['id']}/join", headers=H(tok)).status_code == 200
    play(client, a, "a@example.com", cup["id"], 3)
    play(client, b, "b@example.com", cup["id"], 1)

    board = client.get(f"/api/employer/cups/{cup['id']}", headers=H(te)).json()["leaderboard"]
    top = next(x for x in board if x["position"] == 1)
    joined = next(x for x in board if x["status"] == "joined")
    url = f"/api/employer/cups/{cup['id']}/entries/{{}}/invite"
    assert client.post(url.format(joined["entry_id"]), headers=H(te)).status_code == 409  # решение не оценено

    # пригласить призёра в один клик — пока турнир идёт; вилка кубка, связь с потребностью, доказательство T1
    r = client.post(url.format(top["entry_id"]), headers=H(te))
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["leaderboard"] if x["entry_id"] == top["entry_id"])
    assert row["invited"] and row["candidate_ref"] and row["full_name"] is None
    assert client.post(url.format(top["entry_id"]), headers=H(te)).status_code == 409  # второй раз — нет
    inv = client.get("/api/candidate/invitations", headers=H(a)).json()
    assert len(inv) == 1 and inv[0]["salary_from"] == 220000 and inv[0]["salary_to"] == 300000
    assert "Отборочный турнир ФСП" in str(inv[0]["evidence"])
    from app.modules.invitations.models import Invitation

    with SessionLocal() as db:
        assert str(db.get(Invitation, uuid.UUID(inv[0]["id"])).need_id) == need["id"]

    # чужой работодатель — ни потребности, ни приглашения
    other = employer(client, email="hr2@corp.ru", company="ООО Лютик")
    assert client.post(f"/api/employer/cups/from-need/{need['id']}", headers=H(other)).status_code == 404
    assert client.post(url.format(top["entry_id"]), headers=H(other)).status_code == 404

    # Кабинет ФСП: турнир отдельным списком, только агрегаты
    rep = client.get("/api/fsp-cabinet/report", headers=H(analyst_token(client))).json()
    row = next(x for x in rep["tournaments"] if x["id"] == cup["id"])
    assert row["discipline"] == "Продуктовое программирование" and len(row["tasks"]) == 3
    assert row["participants"] is None  # 3 участника — меньше 5, не раскрывается
    assert "@example.com" not in str(rep["tournaments"]) and "Иван" not in str(rep["tournaments"])

    # итоги: паспорт турнира сохраняется, приглашённого «в один клик» второй раз не приглашают
    fin = client.post(f"/api/employer/cups/{cup['id']}/finish", json={"early": True}, headers=H(te))
    assert fin.status_code == 200, fin.text
    res = fin.json()
    assert res["tournament"]["discipline"] == "Продуктовое программирование" and res["summary"]["placed"] == 2
    assert len(client.get("/api/candidate/invitations", headers=H(a)).json()) == 1
    # после итогов можно запустить новый турнир по той же вакансии
    assert client.post(f"/api/employer/cups/from-need/{need['id']}", headers=H(te)).status_code == 201


def test_tournament_salary_rules(client):
    from app.modules.matching.models import EmployerNeed

    te = employer(client)
    need = _need(client, te)
    with SessionLocal() as db:
        n = db.get(EmployerNeed, uuid.UUID(need["id"]))
        n.salary_from, n.salary_to = 200000, 400000  # шире правила 1,5×
        db.commit()
    r = client.post(f"/api/employer/cups/from-need/{need['id']}", headers=H(te))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "cup_need_salary"
    with SessionLocal() as db:
        n = db.get(EmployerNeed, uuid.UUID(need["id"]))
        n.salary_from = n.salary_to = None
        n.requirements = {**n.requirements, "salary_from": None, "salary_to": None}
        db.commit()
    r = client.post(f"/api/employer/cups/from-need/{need['id']}", headers=H(te))
    assert r.status_code == 201, r.text
    t = r.json()["tournament"]
    assert t["salary"]["source"] == "market" and t["salary"]["basis"] == "net"  # без вилки — рынок категории на руки
    assert client.post(f"/api/employer/cups/from-need/{uuid.uuid4()}", headers=H(te)).status_code == 404
    assert client.post(f"/api/employer/cups/from-need/{need['id']}").status_code == 401


def test_jury_demo_tournament_has_statists_and_one_click_invite(client):
    """Демо жюри: турнир сразу со «статистами» — таблица и приглашение призёра в один клик без ожидания; места есть,
    фактов T1 и записей паспорта у статистов нет; турнир виден ФСП своей песочницы и не виден чужой."""
    from app.modules.demo.seed import seed

    with SessionLocal() as db:  # демо-кандидаты платформы — источник статистов
        seed(db)
        db.commit()
    r = client.post("/api/jury/login", json={"persona": "employer", "scenario": "new"})
    assert r.status_code == 200, r.text
    te = r.json()["access_token"]
    need = _need(client, te)
    r = client.post(f"/api/employer/cups/from-need/{need['id']}", headers=H(te))
    assert r.status_code == 201, r.text
    cup = r.json()
    det = client.get(f"/api/employer/cups/{cup['id']}", headers=H(te)).json()
    board = [x for x in det["leaderboard"] if x["status"] == "scored"]
    assert len(board) >= 5 and board[0]["position"] == 1 and board[0]["score_pct"] == 100
    r = client.post(f"/api/employer/cups/{cup['id']}/entries/{board[0]['entry_id']}/invite", headers=H(te))
    assert r.status_code == 200, r.text
    assert next(x for x in r.json()["leaderboard"] if x["entry_id"] == board[0]["entry_id"])["invited"]
    from app.modules.jury import scope

    sid = scope.parse(client.get("/api/me", headers=H(te)).json()["email"])[1]
    own = client.post("/api/jury/login", json={"persona": "fsp", "scenario": sid})
    assert own.status_code == 200, own.text
    rep = client.get("/api/fsp-cabinet/report", headers=H(own.json()["access_token"])).json()
    assert cup["id"] in [x["id"] for x in rep["tournaments"]]
    alien = client.post("/api/jury/login", json={"persona": "fsp", "scenario": "new"}).json()["access_token"]
    assert cup["id"] not in [x["id"] for x in client.get("/api/fsp-cabinet/report", headers=H(alien)).json()["tournaments"]]
    from app.cup.models import CupEntry
    from app.modules.profiles.models import CandidateFact

    with SessionLocal() as db:  # статисты — без фактов T1 по турниру (места пишутся только при итогах и только своим)
        assert db.scalars(select(CandidateFact).where(CandidateFact.source_ref == f"cup:{cup['id']}")).all() == []
        assert len(db.scalars(select(CupEntry).where(CupEntry.cup_id == uuid.UUID(cup["id"]))).all()) >= 5
