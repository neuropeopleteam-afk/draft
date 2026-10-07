"""И4 «Контакт»: переписка внутри платформы (маскирование контактов до принятия, доступ только двум сторонам,
лимиты, непрочитанные), встречное предложение кандидата, отзыв доступа к контактам, отметка «до вычета НДФЛ /
на руки», правило ширины вилки ≤ 1,5 для вакансий, демо в песочнице жюри, миграция ct01."""
import uuid

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from tests.conftest import register_and_verify
from tests.test_day2_rules import INVITE, H, candidate_with_category, employer, my_ref

MASK = "[контакт скрыт до принятия приглашения]"


def _invite(client, tc, te, **kw) -> dict:
    r = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": my_ref(client, tc), **kw}, headers=H(te))
    assert r.status_code == 201, r.text
    return r.json()


def _post(client, t, kind, tid, body):
    return client.post(f"/api/messages/{kind}/{tid}", json={"body": body}, headers=H(t))


# ------------------------------------------------------------------ правила без БД

@pytest.mark.parametrize("text", [
    "Мой номер +7 912 345-67-89", "звоните 8 (912) 345 67 89", "89123456789", "почта ivan@mail.ru",
    "ivan собака mail точка ru", "пишите t.me/ivan_petrov", "https://wa.me/79123456789", "мой тг ivan_petrov",
    "ник @ivan_petrov", "vk.com/ivan", "восемь девять один два три четыре пять шесть семь", "ivan.petrov.ru",
    "telegram: ivan_p", "ватсап 9123456789", "ivan (at) mail (dot) ru", "skype ivan.petrov", "345-67-89"])
def test_masking_hides_contacts(text):
    from app.modules.contact.masking import mask_contacts

    out, n = mask_contacts(text)
    assert n >= 1 and MASK in out, out


@pytest.mark.parametrize("text", [
    "Вилка 250 000–300 000 ₽", "250000-300000", "ASP.NET Core и .NET 8", "Python 3.12, FastAPI 0.110", "с 01.11.2026",
    "в команде 6 человек, 2 тестировщика", "VK Cloud и Yandex Cloud", "оклад 180000 рублей", "2024-2026 гг.",
    "версия 1.2.3", "до 330 000 ₽ до вычета НДФЛ", "опыт 3,5 года", "Созвонимся в четверг в 11:00", "Node.js и Vue.js"])
def test_masking_keeps_ordinary_text(text):
    from app.modules.contact.masking import mask_contacts

    assert mask_contacts(text) == (text, 0)


def test_ndfl_progressive_scale():
    from app.modules.contact import salary as s

    assert s.net_of(100_000) == 87_000  # 1,2 млн в год — вся сумма по 13 %
    # 3 млн в год: 13 % с 2,4 млн и 15 % с 0,6 млн = 402 000 ₽ налога → 216 500 ₽ в месяц на руки
    assert s.net_of(250_000) == 216_500
    for g in (90_000, 250_000, 600_000, 2_000_000):
        assert abs(s.gross_of(s.net_of(g)) - g) <= 1
    assert s.convert(200_000, "net", "net") == 200_000 and s.to_net(200_000, "net") == 200_000
    assert s.basis_title("gross") == "до вычета НДФЛ" and s.basis_title("net") == "на руки"


def test_trust_salary_check_compares_net_with_market():
    from app.integrations.egrul.trust import salary_check
    from app.modules.catalog.models import Category

    cat = Category(id="backend.middle", title="Backend middle", market_salary_from=200_000, market_salary_to=300_000)
    st, txt = salary_check(250_000, 330_000, cat, "gross")
    assert st == "ok" and "до вычета НДФЛ" in txt and "на руки" in txt
    # 690 тыс. до вычета ≈ 590 тыс. на руки — меньше двух рынков; те же 690 тыс. на руки — больше
    assert salary_check(460_000, 690_000, cat, "gross")[0] == "ok"
    assert salary_check(460_000, 690_000, cat, "net")[0] == "warn"


# ------------------------------------------------------------------ переписка

def test_qa_before_accept_masks_contacts_and_limits(client):
    tc, te = candidate_with_category(client), employer(client)
    inv = _invite(client, tc, te)
    assert inv["thread"] == {"total": 0, "unread": 0}
    r = _post(client, tc, "invitation", inv["id"], "Здравствуйте. Какой стек? Мой номер +7 912 345-67-89, почта ivan@mail.ru")
    assert r.status_code == 201, r.text
    sent = r.json()["sent"]
    assert sent["masked"] == 2 and "345-67-89" not in sent["body"] and "ivan@mail.ru" not in sent["body"]
    assert r.json()["mode"] == "qa"
    th = client.get(f"/api/messages/invitation/{inv['id']}", headers=H(te)).json()
    assert "345-67-89" not in str(th) and th["counterpart"].startswith("Кандидат ") and "Иван" not in str(th)
    # не больше двух сообщений подряд без ответа
    assert _post(client, tc, "invitation", inv["id"], "И ещё: есть ли дежурства?").status_code == 201
    r = _post(client, tc, "invitation", inv["id"], "И третий вопрос")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "qa_limit"
    assert _post(client, te, "invitation", inv["id"], "FastAPI и PostgreSQL. Дежурств нет.").status_code == 201
    assert _post(client, tc, "invitation", inv["id"], "Спасибо").status_code == 201
    # повтор и длина
    assert _post(client, tc, "invitation", inv["id"], "Спасибо").status_code == 409
    r = _post(client, te, "invitation", inv["id"], "а" * 1001)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "message_too_long"
    assert _post(client, te, "invitation", inv["id"], "   ").status_code == 422


def test_qa_limit_per_side(client, monkeypatch):
    from app.modules.contact import service as svc

    monkeypatch.setattr(svc, "QA_MAX_PER_SIDE", 2)
    tc, te = candidate_with_category(client), employer(client)
    inv = _invite(client, tc, te)
    for k in range(2):
        assert _post(client, tc, "invitation", inv["id"], f"Вопрос {k}").status_code == 201
        assert _post(client, te, "invitation", inv["id"], f"Ответ {k}").status_code == 201
    r = _post(client, tc, "invitation", inv["id"], "Вопрос 3")
    assert r.status_code == 409 and "не больше 2" in r.json()["detail"]["message"]


def test_thread_visible_only_to_two_sides(client):
    tc, te = candidate_with_category(client), employer(client)
    inv = _invite(client, tc, te)
    assert _post(client, te, "invitation", inv["id"], "Добрый день").status_code == 201
    tc2 = register_and_verify(client, "other@example.com")
    te2 = employer(client, email="hr2@corp.ru", company="ООО Лютик")
    for t in (tc2, te2):
        assert client.get(f"/api/messages/invitation/{inv['id']}", headers=H(t)).status_code == 404
        assert _post(client, t, "invitation", inv["id"], "Привет").status_code == 404
        assert client.get("/api/messages/threads", headers=H(t)).json() == []
        assert client.get("/api/messages/unread", headers=H(t)).json()["total"] == 0
    assert client.get(f"/api/messages/invitation/{uuid.uuid4()}", headers=H(tc)).status_code == 404
    assert client.get(f"/api/messages/invitation/{inv['id']}").status_code == 401


def test_unread_and_read_marks(client):
    tc, te = candidate_with_category(client), employer(client)
    inv = _invite(client, tc, te)
    _post(client, te, "invitation", inv["id"], "Добрый день. Удобно обсудить задачи команды?")
    assert client.get("/api/messages/unread", headers=H(tc)).json() == {"total": 1, "invitations": 1, "applications": 0}
    assert client.get("/api/messages/unread", headers=H(te)).json()["total"] == 0  # свои не считаются
    lst = client.get("/api/messages/threads", headers=H(tc)).json()
    assert len(lst) == 1 and lst[0]["unread"] == 1 and lst[0]["counterpart"] == "ООО Ромашка"
    cinv = client.get("/api/candidate/invitations", headers=H(tc)).json()[0]
    assert cinv["thread"]["unread"] == 1
    th = client.get(f"/api/messages/invitation/{inv['id']}", headers=H(tc)).json()
    assert th["messages"][0]["mine"] is False
    assert client.get("/api/messages/unread", headers=H(tc)).json()["total"] == 0
    th = client.get(f"/api/messages/invitation/{inv['id']}", headers=H(te)).json()
    assert th["messages"][0]["read_at"] is not None  # работодатель видит, что прочитано


def test_chat_after_accept_without_masking_and_closed_after_decline(client):
    tc, te = candidate_with_category(client), employer(client)
    inv = _invite(client, tc, te)
    assert client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc)).status_code == 200
    r = _post(client, tc, "invitation", inv["id"], "Мой телефон +7 912 345-67-89")
    assert r.status_code == 201 and r.json()["mode"] == "chat" and "345-67-89" in r.json()["sent"]["body"]
    # контакты открыты — работодатель видит в переписке имя, а не обезличенный номер
    th = client.get(f"/api/messages/invitation/{inv['id']}", headers=H(te)).json()
    assert th["counterpart"] == "Иван Петров"
    for k in range(3):  # в чате нет ограничения «вопрос — ответ»
        assert _post(client, tc, "invitation", inv["id"], f"Сообщение {k}").status_code == 201
    tc2 = candidate_with_category(client, email="c2@example.com")
    inv2 = _invite(client, tc2, te)
    client.post(f"/api/candidate/invitations/{inv2['id']}/decline", json={"reason": "Не ищу"}, headers=H(tc2))
    r = _post(client, te, "invitation", inv2["id"], "Жаль")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "thread_closed"
    th = client.get(f"/api/messages/invitation/{inv2['id']}", headers=H(te)).json()
    assert th["can_write"] is False and "только для чтения" in th["reason"]


def test_message_rate_limit(client, monkeypatch):
    from app.modules.contact import service as svc

    monkeypatch.setattr(svc, "RATE_10MIN", 3)
    tc, te = candidate_with_category(client), employer(client)
    inv = _invite(client, tc, te)
    client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc))
    for k in range(3):
        assert _post(client, te, "invitation", inv["id"], f"Сообщение {k}").status_code == 201
    r = _post(client, te, "invitation", inv["id"], "Ещё одно")
    assert r.status_code == 429 and r.json()["detail"]["code"] == "messages_rate"


def test_notifications_push_and_first_unread_email(client, monkeypatch):
    from app.modules.contact import router as cr

    pushes, mails = [], []
    monkeypatch.setattr(cr, "notify_user", lambda uid, title, body, url, tag: pushes.append((title, body, url)))
    monkeypatch.setattr(cr, "notify", lambda email, subject, lines, **kw: mails.append((email, subject)))
    tc, te = candidate_with_category(client), employer(client)
    inv = _invite(client, tc, te)
    _post(client, tc, "invitation", inv["id"], "Вопрос про команду, звоните +7 912 345-67-89")
    _post(client, tc, "invitation", inv["id"], "И про дежурства")
    assert len(pushes) == 2 and all(p[2] == f"/employer/messages?t=invitation:{inv['id']}" for p in pushes)
    assert "345-67-89" not in str(pushes) and pushes[0][0].startswith("Новое сообщение: Кандидат ")
    assert mails == [("hr@corp.ru", pushes[0][0])]  # письмо — только на первое непрочитанное


# ------------------------------------------------------------------ встречное предложение

def test_counter_offer_rules_and_decline(client):
    tc, te = candidate_with_category(client), employer(client)
    inv = _invite(client, tc, te)  # 220 000 – 300 000 до вычета НДФЛ
    url = f"/api/candidate/invitations/{inv['id']}/counter"
    r = client.post(url, json={"salary_from": 250_000, "salary_to": 400_000}, headers=H(tc))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "salary_range_too_wide"
    r = client.post(url, json={"salary_from": 210_000, "salary_to": 290_000}, headers=H(tc))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "counter_not_higher"
    r = client.post(url, json={"salary_from": 460_000, "salary_to": 500_000}, headers=H(tc))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "counter_too_far"
    r = client.post(url, json={"salary_from": 280_000, "salary_to": 340_000, "comment": "Опыт с Kafka"}, headers=H(tc))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["counter"]["status"] == "pending" and body["status"] == "viewed" and body["counters_left"] == 1
    assert client.post(url, json={"salary_from": 290_000, "salary_to": 340_000}, headers=H(tc)).status_code == 409
    emp = client.get("/api/employer/invitations", headers=H(te)).json()[0]
    assert emp["counter"]["salary_from"] == 280_000 and emp["counter"]["comment"] == "Опыт с Kafka"
    assert emp["contacts"] is None
    r = client.post(f"/api/employer/invitations/{inv['id']}/counter/decline", json={"note": "Пока не готовы"},
                    headers=H(te))
    assert r.status_code == 200 and r.json()["status"] == "viewed" and r.json()["salary_from"] == 220_000
    assert r.json()["counter"] is None and r.json()["counters"][0]["status"] == "declined"
    cand = client.get(f"/api/candidate/invitations/{inv['id']}", headers=H(tc)).json()
    assert cand["counters"][0]["employer_note"] == "Пока не готовы"
    hist = [e["status"] for e in cand["history"]]
    assert hist == ["sent", "viewed", "counter_sent", "counter_declined"], hist
    # вторая попытка — и лимит
    assert client.post(url, json={"salary_from": 260_000, "salary_to": 320_000}, headers=H(tc)).status_code == 201
    client.post(f"/api/employer/invitations/{inv['id']}/counter/decline", json={}, headers=H(te))
    r = client.post(url, json={"salary_from": 250_000, "salary_to": 310_000}, headers=H(tc))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "counter_limit"
    # исходное приглашение по-прежнему можно принять
    assert client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc)).json()["status"] == "accepted"


def test_counter_accept_replaces_salary_and_opens_contacts(client):
    tc, te = candidate_with_category(client), employer(client)
    inv = _invite(client, tc, te)
    ref = my_ref(client, tc)
    client.post(f"/api/candidate/invitations/{inv['id']}/counter",
                json={"salary_from": 240_000, "salary_to": 290_000, "salary_basis": "net"}, headers=H(tc))
    te2 = employer(client, email="hr2@corp.ru", company="ООО Лютик")
    assert client.post(f"/api/employer/invitations/{inv['id']}/counter/accept", json={}, headers=H(te2)).status_code == 404
    r = client.post(f"/api/employer/invitations/{inv['id']}/counter/accept", json={"note": "Договорились"}, headers=H(te))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "accepted" and (out["salary_from"], out["salary_to"]) == (240_000, 290_000)
    assert out["salary_basis"] == "net" and out["salary_basis_title"] == "на руки"
    assert out["contacts"]["email"] == "cand@example.com"
    assert client.get(f"/api/employer/candidates/{ref}", headers=H(te)).json()["contacts"] is not None
    hist = [(e["status"], e["by"]) for e in out["history"]]
    assert ("counter_accepted", "employer") in hist and hist[-1] == ("accepted", "employer")
    cand = client.get(f"/api/candidate/invitations/{inv['id']}", headers=H(tc)).json()
    assert cand["counters"][0]["status"] == "accepted" and cand["counters"][0]["offer_from"] == 220_000
    assert client.post(f"/api/employer/invitations/{inv['id']}/counter/accept", json={}, headers=H(te)).status_code == 409


def test_candidate_answer_closes_pending_counter(client):
    tc, te = candidate_with_category(client), employer(client)
    inv = _invite(client, tc, te)
    client.post(f"/api/candidate/invitations/{inv['id']}/counter", json={"salary_from": 250_000, "salary_to": 320_000},
                headers=H(tc))
    out = client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc)).json()
    assert out["status"] == "accepted" and out["salary_to"] == 300_000 and out["counter"] is None
    assert out["counters"][0]["status"] == "withdrawn"
    tc2 = candidate_with_category(client, email="c2@example.com")
    inv2 = _invite(client, tc2, te)
    client.post(f"/api/candidate/invitations/{inv2['id']}/counter", json={"salary_from": 250_000, "salary_to": 320_000},
                headers=H(tc2))
    client.post(f"/api/employer/invitations/{inv2['id']}/withdraw", headers=H(te))
    with SessionLocal() as db:
        from app.modules.contact.models import InvitationCounter

        assert db.scalar(select(InvitationCounter.status).where(
            InvitationCounter.invitation_id == uuid.UUID(inv2["id"]))) == "withdrawn"


# ------------------------------------------------------------------ отзыв доступа к контактам

def test_revoke_and_restore_contacts(client):
    tc, te = candidate_with_category(client), employer(client)
    inv = _invite(client, tc, te)
    ref = my_ref(client, tc)
    url = f"/api/candidate/invitations/{inv['id']}/contacts"
    assert client.post(f"{url}/revoke", headers=H(tc)).status_code == 409  # не принято
    client.post(f"/api/candidate/invitations/{inv['id']}/accept", headers=H(tc))
    assert client.get(f"/api/employer/candidates/{ref}", headers=H(te)).json()["contacts"]["phone"]
    r = client.post(f"{url}/revoke", headers=H(tc))
    assert r.status_code == 200 and r.json()["contacts_revoked"] is True
    detail = client.get(f"/api/employer/candidates/{ref}", headers=H(te)).json()
    assert detail["contacts"] is None and detail["contacts_revoked"] is True and "отозвал" in detail["contacts_note"]
    assert "Иван" not in str(detail) and "111-22-33" not in str(detail)
    emp = client.get("/api/employer/invitations", headers=H(te)).json()[0]
    assert emp["status"] == "accepted" and emp["contacts"] is None and emp["contacts_revoked"] is True
    assert [e["status"] for e in emp["history"]][-1] == "contacts_revoked"
    assert client.post("/api/employer/ats/stub/connect", json={}, headers=H(te)).status_code == 200
    r = client.post("/api/employer/ats/push", json={"invitation_id": inv["id"]}, headers=H(te))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "contacts_revoked"
    # переписка снова «вопрос — ответ» с маскированием, собеседник у работодателя — снова обезличен
    r = _post(client, te, "invitation", inv["id"], "Почему? Напишите на hr@corp.ru")
    assert r.status_code == 201 and r.json()["mode"] == "qa" and "hr@corp.ru" not in r.json()["sent"]["body"]
    th = client.get(f"/api/messages/invitation/{inv['id']}", headers=H(te)).json()
    assert th["counterpart"] == f"Кандидат {ref}" and "Иван" not in str(th)
    assert client.post(f"{url}/revoke", headers=H(tc)).status_code == 409
    r = client.post(f"{url}/restore", headers=H(tc))
    assert r.status_code == 200 and r.json()["contacts_revoked"] is False
    assert client.get(f"/api/employer/candidates/{ref}", headers=H(te)).json()["contacts"]["email"] == "cand@example.com"
    assert client.post(f"{url}/restore", headers=H(tc)).status_code == 409
    tc2 = register_and_verify(client, "other@example.com")
    assert client.post(f"{url}/revoke", headers=H(tc2)).status_code == 404


# ------------------------------------------------------------------ НДФЛ и вилки

def test_salary_basis_in_invitation_probe_and_minimum(client):
    tc, te = candidate_with_category(client), employer(client)  # скрытый минимум 250 000 на руки
    inv = _invite(client, tc, te, salary_from=230_000, salary_to=280_000)
    assert inv["salary_basis"] == "gross" and inv["salary_basis_title"] == "до вычета НДФЛ"
    cand = client.get(f"/api/candidate/invitations/{inv['id']}", headers=H(tc)).json()
    assert cand["below_my_minimum"] is True  # 280 000 до вычета ≈ 243 600 на руки < 250 000
    tc2 = candidate_with_category(client, email="c2@example.com")
    inv2 = _invite(client, tc2, te, salary_from=230_000, salary_to=280_000, salary_basis="net")
    assert inv2["salary_basis_title"] == "на руки"
    assert client.get(f"/api/candidate/invitations/{inv2['id']}", headers=H(tc2)).json()["below_my_minimum"] is False
    r = client.post("/api/employer/invitations", json={**INVITE, "candidate_ref": my_ref(client, tc2),
                                                       "salary_basis": "чистыми"}, headers=H(te))
    assert r.status_code == 422


def test_vacancy_salary_width_and_basis(client):
    te = employer(client)
    base = {"title": "Python-разработчик", "category_id": "backend.middle", "description": "API платёжного сервиса",
            "stack": ["python"], "work_format": "remote"}
    r = client.post("/api/employer/vacancies", json={**base, "salary_from": 100_000, "salary_to": 200_000}, headers=H(te))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "salary_range_too_wide"
    r = client.post("/api/employer/vacancies", json={**base, "salary_from": 150_000, "salary_to": 220_000,
                                                     "salary_basis": "net"}, headers=H(te))
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["salary_basis"] == "net" and v["salary_basis_title"] == "на руки"
    r = client.patch(f"/api/employer/vacancies/{v['id']}", json={"salary_to": 260_000}, headers=H(te))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "salary_range_too_wide"
    r = client.patch(f"/api/employer/vacancies/{v['id']}", json={"salary_basis": "gross"}, headers=H(te))
    assert r.status_code == 200 and r.json()["salary_basis"] == "gross"


def test_demo_vacancies_follow_width_rule():
    from app.integrations.vacancies.demo import VACANCIES
    from app.modules.invitations.service import SALARY_MAX_RATIO

    assert all(row[5] <= SALARY_MAX_RATIO * row[4] for row in VACANCIES)


def test_vacancy_application_chat(client):
    tc, te = candidate_with_category(client), employer(client)
    v = client.post("/api/employer/vacancies", json={
        "title": "Python-разработчик", "category_id": "backend.middle", "description": "API платёжного сервиса",
        "stack": ["python"], "work_format": "remote", "salary_from": 200_000, "salary_to": 280_000}, headers=H(te)).json()
    a = client.post(f"/api/vacancies/{v['id']}/apply", json={"consent_contacts": True}, headers=H(tc)).json()
    r = _post(client, te, "application", a["id"], "Спасибо за отклик. Удобно созвониться? Наш номер +7 495 123-45-67")
    assert r.status_code == 201 and r.json()["mode"] == "chat" and "123-45-67" in r.json()["sent"]["body"]
    assert client.get("/api/messages/unread", headers=H(tc)).json() == {"total": 1, "invitations": 0, "applications": 1}
    # сводка переписки в карточках отклика у обеих сторон (для счётчика непрочитанных в списках)
    mine = client.get("/api/candidate/applications", headers=H(tc)).json()[0]
    assert mine["thread"] == {"total": 1, "unread": 1}
    apps = client.get(f"/api/employer/vacancies/{v['id']}/applications", headers=H(te)).json()
    assert apps[0]["thread"] == {"total": 1, "unread": 0}
    th = client.get(f"/api/messages/application/{a['id']}", headers=H(tc)).json()
    assert th["title"] == "Python-разработчик" and th["counterpart"] == "ООО Ромашка"
    assert client.get("/api/candidate/applications", headers=H(tc)).json()[0]["thread"]["unread"] == 0
    te2 = employer(client, email="hr2@corp.ru", company="ООО Лютик")
    assert client.get(f"/api/messages/application/{a['id']}", headers=H(te2)).status_code == 404
    client.post(f"/api/candidate/applications/{a['id']}/withdraw", headers=H(tc))
    r = _post(client, te, "application", a["id"], "Жаль")
    assert r.status_code == 409


def test_cup_and_probe_keep_salary_basis(client):
    tc, te = candidate_with_category(client), employer(client)
    r = client.post("/api/employer/probes", json={
        "candidate_refs": [my_ref(client, tc)], "title": "Мини-задача", "task_text": "Опишите индекс в PostgreSQL",
        "answer_mode": "any", "salary_from": 200_000, "salary_to": 260_000, "salary_basis": "net",
        "time_limit_min": 30}, headers=H(te))
    assert r.status_code == 201, r.text
    probes = client.get("/api/candidate/probes", headers=H(tc)).json()
    assert probes[0]["salary_basis"] == "net" and probes[0]["salary_basis_title"] == "на руки"


# ------------------------------------------------------------------ демо жюри и миграция

def test_jury_sandbox_has_contact_demo(client):
    from app.modules.demo.seed import seed

    with SessionLocal() as db:
        seed(db)
        db.commit()
    r = client.post("/api/jury/login", json={"persona": "candidate_nofsp", "scenario": "new"})
    assert r.status_code == 200, r.text
    ilya, sid = r.json()["access_token"], r.json()["scenario"]
    inv = client.get("/api/candidate/invitations", headers=H(ilya)).json()[0]
    assert inv["thread"] == {"total": 2, "unread": 1}
    th = client.get(f"/api/messages/invitation/{inv['id']}", headers=H(ilya)).json()
    assert MASK in th["messages"][0]["body"] and "345-67-89" not in str(th)
    e = client.post("/api/jury/login", json={"persona": "employer", "scenario": sid}).json()["access_token"]
    invs = client.get("/api/employer/invitations", headers=H(e)).json()
    assert any(i["counter"] and i["counter"]["status"] == "pending" for i in invs)
    rv = next(i for i in invs if i["contacts_revoked"])
    # дата отзыва согласована с событием истории (демо датировано задним числом)
    ev = next(e for e in rv["history"] if e["status"] == "contacts_revoked")
    assert rv["contacts_revoked_at"][:16] == ev["at"][:16]
    assert any(i["status"] == "accepted" and i["thread"]["unread"] == 1 for i in invs)
    assert client.get("/api/messages/unread", headers=H(e)).json()["total"] >= 1
    # Мария: отклик на вакансию компании жюри с перепиской — виден обеим сторонам; вакансия песочницы видна
    # только в своей песочнице и не попадает в общий список
    from app.modules.contact.demo import DEMO_VACANCY

    maria = client.post("/api/jury/login", json={"persona": "candidate", "scenario": sid}).json()["access_token"]
    mine = client.get("/api/candidate/applications", headers=H(maria)).json()
    assert [a["vacancy_title"] for a in mine] == [DEMO_VACANCY] and mine[0]["thread"] == {"total": 3, "unread": 1}
    assert client.get("/api/messages/unread", headers=H(maria)).json()["applications"] == 1
    vac = client.get("/api/employer/vacancies", headers=H(e)).json()
    assert [v["title"] for v in vac] == [DEMO_VACANCY] and vac[0]["applications"]["total"] == 1
    apps = client.get(f"/api/employer/vacancies/{vac[0]['id']}/applications", headers=H(e)).json()
    assert apps[0]["thread"] == {"total": 3, "unread": 0} and apps[0]["contacts"]["full_name"]
    assert any(t["kind"] == "application" for t in client.get("/api/messages/threads", headers=H(e)).json())
    ids = lambda tok: {v["id"] for v in client.get("/api/vacancies?limit=100", headers=H(tok)).json()["items"]}  # noqa: E731
    assert vac[0]["id"] in ids(maria)
    other = client.post("/api/jury/login", json={"persona": "candidate", "scenario": "new"}).json()["access_token"]
    assert vac[0]["id"] not in ids(other)  # у другой песочницы — своя копия, чужая не видна
    assert vac[0]["id"] not in ids(candidate_with_category(client))  # обычному кандидату — тоже
    # демо-кандидаты не из первой пятёрки подборок песочницы
    from app.modules.contact.demo import shared_candidates
    from app.modules.matching.models import EmployerNeed

    mine = {"Backend-разработчик (интеграции с банками)", "Python-разработчик (платёжный шлюз)",
            "Backend-разработчик (антифрод)"}
    refs = {i["candidate_ref"] for i in invs if i["position_title"] in mine}
    assert len(refs) == 3
    with SessionLocal() as db:
        ids = [uuid.UUID(n["id"]) for n in client.get("/api/employer/needs", headers=H(e)).json()]
        needs = db.scalars(select(EmployerNeed).where(EmployerNeed.id.in_(ids))).all()
        assert needs and {p.public_ref for p in shared_candidates(db, needs)} <= refs
    for n in client.get("/api/employer/needs", headers=H(e)).json():
        top = client.get(f"/api/employer/needs/{n['id']}/selections/1", headers=H(e)).json()["results"][:5]
        assert not {c["ref"] for c in top} & refs


def test_migration_ct01_up_and_down(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, inspect

    from tests.conftest import alembic_config

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "ct01")
    insp = inspect(create_engine(url))
    assert {"contact_messages", "invitation_counters"} <= set(insp.get_table_names())
    for t in ("invitations", "probes", "vacancies", "cups"):
        assert "salary_basis" in {c["name"] for c in insp.get_columns(t)}
    command.downgrade(cfg, "qr01")
    insp = inspect(create_engine(url))
    assert "contact_messages" not in insp.get_table_names()
    assert "salary_basis" not in {c["name"] for c in insp.get_columns("invitations")}
