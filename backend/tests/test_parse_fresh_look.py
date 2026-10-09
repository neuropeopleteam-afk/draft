"""И27 + «свежий взгляд жюри» (И20, <внутренний документ>, Н1, Н2, Н4): три собственных текста эксперта.

Н1 — отрицание не становится требованием («фронтенд не нужен» → не Frontend; «Python или Java не нужен» → не
обязательные Python/Java; «докер не обязателен, но плюс» → желательно). Н2 — требования вне справочника не теряются:
словарь («1С», Terraform, Excel, Power BI) и модель (unknown_required, с цитатой) → «вне справочника — проверить
вручную», сохраняются в потребности и видны в версии подборки. Н4 — один фрагмент «REST» даёт одно требование.
Сеть не используется: транспорт httpx подменён (tests/test_llm_chain.py).
"""
from __future__ import annotations

import json

from app.modules.matching.need_parser import _same_fragment, parse_need, parse_rules
from tests.test_day2_rules import H, employer
from tests.test_llm_chain import configure, net, reply  # noqa: F401 — фикстура net

NORMAL = ("Нужен Middle backend-разработчик для B2B API: обязательно Python, FastAPI, PostgreSQL. Команда делает сервис "
          "логистики; важны проектирование REST, SQL и работа с транзакциями. Удалённо, Москва, 180000–240000 рублей. "
          "Docker будет плюсом, опыт ФСП не обязателен.")
SLANG = ("ишем мидл бэк на питоне: фаст апи, постгрес. пилить апишку для логистики, уметь SQL и REST. докер не "
         "обязателен, но плюс. фронтенд не нужен. удаленка, мск, 180–240к на руки.")
UNSUP = ("Нужен DevOps/1С/аналитик для сопровождения ERP и отчётности: обязательно Kubernetes, Terraform, "
         "1С:Предприятие, SQL, Excel и Power BI. Разработчик Python или Java не нужен. Middle, удалённо, "
         "180000–250000 рублей. Нужен именно DevOps с опытом 1С и аналитики, не обычный Backend.")
EMPTY = {"stack_required": [], "stack_desired": [], "confirm": [], "remove": [], "unknown_required": [],
         "direction": None, "grade": None, "experience_years_min": None, "work_format": None,
         "quotes": {"direction": None, "grade": None, "experience_years_min": None, "work_format": None}}


def _tags(r: dict) -> tuple[set[str], set[str]]:
    return {i["tag"] for i in r["stack_required"]}, {i["tag"] for i in r["stack_desired"]}


def _model(monkeypatch, net, delta: dict) -> None:
    configure(monkeypatch, LLM_CHAIN="openrouter")
    net.on("or.test", None, lambda req, body: reply(json.dumps({**EMPTY, **delta}, ensure_ascii=False), body["model"]))


# ------------------------------------------------------------------ Н1: отрицания
def test_n1_slang_text_of_expert():
    r = parse_need(SLANG, use_llm=False)
    assert r["direction"] == "backend" and r["grade"] == "middle"  # было: Frontend из «фронтенд не нужен»
    req, des = _tags(r)
    assert {"python", "fastapi", "postgresql", "sql"} <= req  # «фаст апи» — сленг FastAPI
    assert "docker" in des and not r["excluded"]  # «докер не обязателен, но плюс» — желательно, не исключение
    assert r["evidence"]["direction"]["quote"].lower() == "бэк"


def test_n1_negated_languages_are_excluded():
    r = parse_need(UNSUP, use_llm=False)
    req, des = _tags(r)
    assert not {"python", "java"} & (req | des)
    assert {x["tag"] for x in r["excluded"]} == {"python", "java"}


def test_n1_negated_direction_variants():
    for text in ("Python-разработчик middle: Django, PostgreSQL. Фронтенд не нужен.",
                 "Ищем бэкенд на Go без фронтенда: gRPC, PostgreSQL",
                 "Нужен бэк на Java, не нужен frontend: Spring, Kafka"):
        assert parse_rules(text)["direction"] == "backend", text
    assert parse_rules("Фронтенд-разработчик: React, TypeScript")["direction"] == "frontend"
    assert parse_rules("Тестировщик не нужен, нужен Python-разработчик: Django")["direction"] == "backend"


def test_n1_model_cannot_return_excluded_tag(monkeypatch, net):
    _model(monkeypatch, net, {"stack_required": [{"tag": "java", "weight": 0.8, "quote": "Java не нужен"}]})
    req, des = _tags(parse_need(UNSUP))
    assert "java" not in req | des


# ------------------------------------------------------------------ Н2: вне справочника
def test_n2_unknown_required_kept_by_rules():
    r = parse_need(UNSUP, use_llm=False)
    assert {"1С", "Terraform", "Excel", "Power BI"} <= {u["term"] for u in r["unknown_terms"]}
    assert all(u["evidence"]["quote"] for u in r["unknown_terms"])
    assert r["coverage"]["role"] == "devops" and r["direction"] == "backend"  # ближайшая, частичное соответствие


def test_n2_unknown_from_model_saved_and_in_selection(client, monkeypatch, net):
    _model(monkeypatch, net, {"unknown_required": [
        {"term": "ERP", "quote": "сопровождения ERP"},       # вне справочника — сохраняем с цитатой
        {"term": "Kubernetes", "quote": "Kubernetes"},       # тег справочника — не «вне справочника»
        {"term": "Terraform", "quote": "Terraform"},         # уже найдено словарём — не дублируем
        {"term": "Ansible", "quote": "Ansible для конфигураций"}]})  # цитаты нет в тексте — отбрасываем
    r = parse_need(UNSUP)
    terms = {u["term"]: u["evidence"] for u in r["unknown_terms"]}
    assert terms["ERP"]["source"] == "llm" and terms["ERP"]["quote"] == "ERP" and terms["ERP"]["model"]
    assert "Kubernetes" not in terms and "Ansible" not in terms
    assert sum(u["term"] == "Terraform" for u in r["unknown_terms"]) == 1
    t = employer(client)
    body = {k: v for k, v in r.items() if k not in ("method", "bias", "suggested_text", "llm", "salary_net")}
    n = client.post("/api/employer/needs", json={"text": UNSUP, "requirements": body}, headers=H(t))
    assert n.status_code == 201, n.text
    saved = {u["term"]: u["evidence"]["source"] for u in n.json()["requirements"]["unknown_terms"]}
    assert saved["ERP"] == "llm" and saved["Terraform"] == "rules" and "1С" in saved
    s = client.get(f"/api/employer/needs/{n.json()['id']}/selections/1", headers=H(t)).json()
    assert "ERP" in {u["term"] for u in s["requirements"]["unknown_terms"]}
    assert s["requirements"]["coverage"]["role"] == "devops"  # частичность доходит до версии подборки


def test_n2_forged_unknown_without_quote_is_dropped(client):
    t = employer(client)
    req = parse_need(NORMAL, use_llm=False)
    body = {k: v for k, v in req.items() if k not in ("method", "bias", "suggested_text", "llm", "salary_net")}
    body["unknown_terms"] = [{"term": "Haskell", "evidence": {"quote": "Haskell", "source": "llm"}}]
    n = client.post("/api/employer/needs", json={"text": NORMAL, "requirements": body}, headers=H(t))
    assert n.status_code == 201, n.text
    assert not n.json()["requirements"]["unknown_terms"]  # термина нет в тексте — заметка не создаётся


# ------------------------------------------------------------------ Н4: REST
def test_n4_rest_is_one_requirement(monkeypatch, net):
    req, _ = _tags(parse_need(NORMAL, use_llm=False))
    assert "http" in req and "rest-api" not in req
    _model(monkeypatch, net, {"stack_required": [{"tag": "rest-api", "weight": 0.8, "quote": "проектирование REST"}],
                              "remove": [{"tag": "http", "reason": "упомянут только REST", "quote": "проектирование REST"}]})
    r = parse_need(NORMAL)
    req, des = _tags(r)
    assert "http" in req and "rest-api" not in req | des
    assert r["llm_remove"] == [] and r["llm"]["same_fragment"] == 1


def test_n4_own_mention_is_not_a_duplicate():
    text = "Frontend: React/Next.js и TypeScript"
    rules = parse_rules(text)
    s = text.index("React/Next.js")
    item = {"tag": "nextjs", "evidence": {"start": s, "end": s + len("React/Next.js")}}
    assert _same_fragment(text, item, rules) == set()  # Next.js в цитате — самостоятельное требование
    item = {"tag": "redux", "evidence": {"start": s, "end": s + len("React")}}
    assert _same_fragment(text, item, rules) == {"react"}
