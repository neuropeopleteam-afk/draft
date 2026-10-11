"""Основание вилки потребности («на руки» / до вычета НДФЛ) не теряется при подтверждении разбора и редактировании.

Находка независимой проверки (11.10, выкладка 5): разбор текста отдавал ``salary_net=True`` для «180–230 тыс. на руки»,
но тело подтверждения с клиента поле не содержало (``reqBody`` выбрасывал его как служебное), а серверная модель
``Requirements`` его не знала → ``normalize`` записывал ``False``: сохранённая потребность, приглашение из подборки,
сравнение и взаимный подбор считали вилку «до вычета». Теперь ``salary_net`` — поле требований: явное значение сохраняется,
отсутствующее — восстанавливается по тексту потребности (как при разборе).
"""
from __future__ import annotations

from app.modules.matching.need_parser import parse_need
from app.modules.mutual.service import need_salary_basis as need_basis
from tests.test_day2_rules import H, employer

NET_TEXT = ("Ищем middle backend-разработчика на Python: обязательно Python и PostgreSQL, желательно Docker. "
            "Удалённо. 180–230 тыс. рублей на руки.")
GROSS_TEXT = ("Ищем middle backend-разработчика на Python: обязательно Python и PostgreSQL, желательно Docker. "
              "Удалённо. 180–230 тыс. рублей до вычета НДФЛ.")


def _client_body(r: dict, keep_net: bool) -> dict:
    """Тело подтверждения как с фронтенда: служебные поля разбора убраны; salary_net — по флагу (старый клиент его терял)."""
    drop = {"method", "bias", "suggested_text", "llm", "llm_remove", "llm_suggest", "excluded", "salary_note",
            "coverage", "parse_job", "delta"} | (set() if keep_net else {"salary_net"})
    return {k: v for k, v in r.items() if k not in drop}


def _create(client, token: str, text: str, body: dict) -> dict:
    n = client.post("/api/employer/needs", json={"text": text, "requirements": body}, headers=H(token))
    assert n.status_code == 201, n.text
    return n.json()


def test_parse_gives_basis_for_both_texts():
    assert parse_need(NET_TEXT, use_llm=False)["salary_net"] is True
    assert parse_need(GROSS_TEXT, use_llm=False)["salary_net"] is False


def test_confirmed_need_keeps_net_basis_from_client(client):
    t = employer(client)
    r = parse_need(NET_TEXT, use_llm=False)
    n = _create(client, t, NET_TEXT, _client_body(r, keep_net=True))
    saved = n["requirements"]
    assert (saved["salary_from"], saved["salary_to"], saved["salary_net"]) == (180_000, 230_000, True)
    # после перечитывания — то же основание; взаимный подбор читает его как «на руки»
    again = client.get(f"/api/employer/needs/{n['id']}", headers=H(t)).json()["requirements"]
    assert again["salary_net"] is True and need_basis(again) == "net"
    # условия версии подборки — те же номинальные суммы
    s = client.get(f"/api/employer/needs/{n['id']}/selections/1", headers=H(t)).json()
    assert s["requirements"]["salary_net"] is True
    assert (s["requirements"]["salary_from"], s["requirements"]["salary_to"]) == (180_000, 230_000)


def test_old_client_without_field_gets_basis_from_text(client):
    """Клиент, который поле не передаёт (прежний reqBody), не превращает «на руки» в «до вычета»."""
    t = employer(client)
    r = parse_need(NET_TEXT, use_llm=False)
    assert "salary_net" not in _client_body(r, keep_net=False)
    n = _create(client, t, NET_TEXT, _client_body(r, keep_net=False))
    assert n["requirements"]["salary_net"] is True
    g = _create(client, t, GROSS_TEXT, _client_body(parse_need(GROSS_TEXT, use_llm=False), keep_net=False))
    assert g["requirements"]["salary_net"] is False


def test_explicit_basis_wins_over_text_and_survives_edit(client):
    """Явное значение работодателя — сильнее текста; правка вилки без основания основание не сбрасывает."""
    t = employer(client)
    r = parse_need(GROSS_TEXT, use_llm=False)
    n = _create(client, t, GROSS_TEXT, {**_client_body(r, keep_net=True), "salary_net": True})
    assert n["requirements"]["salary_net"] is True
    # редактирование: клиент присылает требования с основанием — остаётся; без основания — по тексту (до вычета)
    body = {**_client_body(n["requirements"], keep_net=True), "salary_to": 240_000}
    p = client.patch(f"/api/employer/needs/{n['id']}", json={"requirements": body}, headers=H(t))
    assert p.status_code == 200, p.text
    assert p.json()["requirements"]["salary_net"] is True and p.json()["requirements"]["salary_to"] == 240_000
    one_sided = {**_client_body(n["requirements"], keep_net=True), "salary_from": None, "salary_to": 240_000}
    p2 = client.patch(f"/api/employer/needs/{n['id']}", json={"requirements": one_sided}, headers=H(t))
    assert p2.status_code == 200, p2.text
    assert p2.json()["requirements"]["salary_net"] is True and p2.json()["requirements"]["salary_from"] is None


def test_no_salary_means_no_basis(client):
    t = employer(client)
    text = "Ищем middle backend-разработчика на Python: обязательно Python и PostgreSQL. Удалённо."
    r = parse_need(text, use_llm=False)
    n = _create(client, t, text, _client_body(r, keep_net=True))
    assert n["requirements"]["salary_from"] is None and n["requirements"]["salary_net"] is None
