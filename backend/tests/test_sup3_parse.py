"""Находки прохода стенда (С3-1…С3-3, выкладка 3): разбор потребности проверяющего на стенде 580b982.

Текст супервизора (sup2_shots/b23): «Офис в Москве … опыт не требуется … Удалёнка не предусмотрена …» — было: формат
«удалённо или офис/гибрид», опыт 0 без цитаты («добавлено вручную»), веса одного перечисления 1,0/0,9/0,8/0,56 у
словаря и 0,85/0,53 после усреднения с моделью. Стало: формат «офис» (Москва), опыт 0 с цитатой «опыт не требуется»,
веса — по одному правилу у словаря и после модели (вес словаря не усредняется с весом модели; добавленному моделью
навыку — вес по тому же правилу), правило показано у весов. По умолчанию правило прежнее — по порядку упоминания
(ORDER_WEIGHT_RULE); «один вес на перечисление» (LIST_WEIGHT_RULE) — за флагом NEED_LIST_WEIGHTS=1: на бенчмарке он
даёт MRR −0,005 (docs/LLM.md). Сеть не используется: транспорт httpx подменён (tests/test_llm_chain.py).
"""
from __future__ import annotations

import json

import pytest

from app.modules.matching import fast_parse
from app.modules.matching.need_parser import (LIST_WEIGHT_RULE, ORDER_WEIGHT_RULE, enumerations, experience_span,
                                              parse_conditions, parse_need, parse_rules)
from tests.test_day2_rules import H, employer
from tests.test_llm_chain import configure, net, reply  # noqa: F401 — фикстура net

SUP3 = ("Офис в Москве, график 10–19 по мск. Нужен Python-разработчик (Django, PostgreSQL, Docker), опыт не требуется — "
        "рассмотрим junior с пет-проектами. Удалёнка не предусмотрена. Будет плюсом Redis. Вилка 120–160 тыс. ₽. "
        "Вопросы: HR Ольга, +7 999 123-45-67, ул. Тверская, д. 7, офис 15")
EMPTY = {"stack_required": [], "stack_desired": [], "confirm": [], "remove": [], "unknown_required": [],
         "direction": None, "grade": None, "experience_years_min": None, "work_format": None,
         "quotes": {"direction": None, "grade": None, "experience_years_min": None, "work_format": None}}


def _w(r: dict, zone: str = "stack_required") -> dict[str, float]:
    return {i["tag"]: i["weight"] for i in r[zone]}


# ------------------------------------------------------------------ С3-1: отрицание формата
def test_supervisor_text_rules():
    r = parse_need(SUP3, use_llm=False)
    assert (r["work_format"], r["work_formats"], r["city"]) == ("office", None, "Москва")
    assert r["experience_years_min"] == 0.0
    assert r["evidence"]["experience_years_min"]["quote"] == "опыт не требуется"  # С3-2: цитата есть
    assert _w(r) == {"python": 1.0, "django": 0.9, "postgresql": 0.8, "docker": 0.56}  # С3-3: по правилу, не 0,85/0,53
    assert _w(r, "stack_desired") == {"redis": 0.3}
    assert r["weight_rule"] == ORDER_WEIGHT_RULE and "×0,8" in r["weight_rule"]


def test_supervisor_text_list_flag(monkeypatch):
    monkeypatch.setenv("NEED_LIST_WEIGHTS", "1")
    r = parse_need(SUP3, use_llm=False)
    assert _w(r) == {"python": 1.0, "django": 1.0, "postgresql": 1.0, "docker": 1.0}  # одно перечисление — один вес
    assert r["weight_rule"] == LIST_WEIGHT_RULE


@pytest.mark.parametrize("text,allowed", [
    ("Удалёнка не предусмотрена, офис в Москве.", ["office"]),
    ("Офис в Казани. Без удалёнки.", ["office"]),
    ("Только офис, Москва.", ["office"]),
    ("Работа исключительно из офиса в Москве, гибрид обсуждается после испытательного.", ["office"]),
    ("Удалённой работы нет, гибрид в Москве.", ["hybrid"]),
    ("Гибрид в Москве. Удалённый формат у нас не практикуется.", ["hybrid"]),
    ("Офис в Москве, удалённо не работаем.", ["office"]),
    ("Remote is not possible, office in Moscow.", ["office"]),
    ("Удалёнка или офис в Москве.", ["remote", "office", "hybrid"]),  # прежнее объединение «или» сохранилось
    ("Работа удалённо. Адрес для документов: ул. Ленина, д. 1, офис 15.", ["remote"]),  # «офис 15» — адрес
    ("Офис 3 дня в неделю, остальное удалённо.", ["hybrid", "office"]),  # «офис 3 дня» — формат, не адрес
])
def test_format_negation(text, allowed):
    c = parse_conditions(text)
    assert (c["work_formats"] or [c["work_format"]]) == allowed
    assert set(c["formats_excluded"]) == {"office", "hybrid", "remote"} - set(allowed)


# ------------------------------------------------------------------ С3-2: «опыт не требуется» → 0 с цитатой
@pytest.mark.parametrize("text,years,quote", [
    ("Python, опыт не требуется.", 0.0, "опыт не требуется"),
    ("Опыт работы: не требуется", 0.0, "Опыт работы: не требуется"),
    ("Опыт не обязателен, научим.", 0.0, "Опыт не обязателен"),
    ("Можно без опыта, Python.", 0.0, "Можно без опыта"),
    ("Рассмотрим студентов без опыта работы.", 0.0, "Рассмотрим студентов без опыта работы"),
    ("Junior без опыта, Python.", 0.0, "без опыта"),
    ("Без опыта кандидаты не рассматриваются. Опыт от 2 лет.", 2.0, None),
    ("Без опыта, к сожалению, не рассматриваем.", None, None),
    ("Не возьмём без опыта: опыт от 1 года.", 1.0, None),
    ("Опыт работы с Kafka не требуется, Python от 3 лет.", 3.0, None),  # про технологию, не про опыт вообще
])
def test_zero_experience(text, years, quote):
    v, span = experience_span(text)
    assert v == years
    if quote:
        assert text[span[0]:span[1]] == quote


# ------------------------------------------------------------------ С3-3: веса по перечислениям (флаг)
def test_list_weights_rule(monkeypatch):
    monkeypatch.setenv("NEED_LIST_WEIGHTS", "1")
    t = ("Требования:\n- Python\n- Django; PostgreSQL\n- Docker\n\nТакже нужно знание Kafka и Redis.\n"
         "Обязательно Git. Будет плюсом: Celery, Kubernetes.")
    assert len(enumerations(t)) == 4  # список под заголовком — одно перечисление
    r = parse_rules(t)
    assert _w(r) == {"python": 1.0, "django": 1.0, "postgresql": 1.0, "docker": 1.0, "kafka": 0.9, "redis": 0.9,
                     "git": 0.8}
    assert set(_w(r, "stack_desired").values()) == {0.3}
    assert "одно предложение или один список" in LIST_WEIGHT_RULE


def test_default_is_old_order_rule(monkeypatch):
    monkeypatch.delenv("NEED_LIST_WEIGHTS", raising=False)
    t = "Требования: Python, Django. Также нужно знание Kafka и Git."
    assert _w(parse_rules(t)) == {"python": 1.0, "django": 0.9, "kafka": 0.8, "git": 0.56}


def test_floor_is_point_six(monkeypatch):
    monkeypatch.setenv("NEED_LIST_WEIGHTS", "1")
    t = ". ".join(f"Обязательно {x}" for x in ("Python", "Django", "Redis", "Kafka", "PostgreSQL", "Docker", "Linux")) + "."
    assert list(_w(parse_rules(t)).values()) == [1.0, 0.9, 0.8, 0.7, 0.6, 0.6, 0.6]


# ------------------------------------------------------------------ путь модели: те же правила
def _model(monkeypatch, net, delta: dict) -> None:
    configure(monkeypatch, LLM_CHAIN="openrouter")
    net.on("or.test", None, lambda req, body: reply(json.dumps({**EMPTY, **delta}, ensure_ascii=False), body["model"]))


@pytest.mark.parametrize("flag,weights", [
    ("0", {"python": 1.0, "django": 0.9, "postgresql": 0.8, "docker": 0.56}),
    ("1", {"python": 1.0, "django": 1.0, "postgresql": 1.0, "docker": 1.0})])
def test_model_weights_are_not_averaged(monkeypatch, net, flag, weights):
    # модель ставит Django 0,8 и Docker 0,5 (как на стенде: было 0,85 / 0,53) и предлагает «удалённо» и «опыт от
    # 1 года» — веса словаря остаются по правилу, исключённый текстом формат не предлагается
    monkeypatch.setenv("NEED_LIST_WEIGHTS", flag)
    _model(monkeypatch, net, {
        "stack_required": [{"tag": "django", "weight": 0.8, "quote": "Django"}, {"tag": "docker", "weight": 0.5,
                                                                                  "quote": "Docker"}],
        "confirm": ["python", "django", "postgresql", "docker"], "work_format": "remote", "experience_years_min": 1,
        "quotes": {**EMPTY["quotes"], "work_format": "Удалёнка", "experience_years_min": "junior с пет-проектами"}})
    r = parse_need(SUP3)
    assert r["method"] == "llm+rules"
    assert _w(r) == weights
    assert r["work_format"] == "office" and r["experience_years_min"] == 0.0
    assert not [s for s in r["llm_suggest"] if s["field"] == "work_format"]


def test_model_does_not_suggest_excluded_format(monkeypatch, net):
    t = "Удалёнка не предусмотрена. Python-разработчик, Django."
    assert parse_rules(t)["work_formats"] == ["office", "hybrid"]  # только исключение: офис или гибрид
    _model(monkeypatch, net, {"work_format": "remote", "quotes": {**EMPTY["quotes"], "work_format": "Удалёнка"}})
    r = parse_need(t)
    assert r["work_format"] == "office" and r["work_formats"] == ["office", "hybrid"]
    assert not [s for s in r["llm_suggest"] if s["field"] == "work_format"]  # «удалённо вместо офис» не предлагается


def test_fast_parse_job_weights_by_rule(client, monkeypatch, net):
    """Фоновое уточнение (И27): добавленный моделью навык — с весом по правилу по месту в тексте (3-й → 0,8), не 0,4
    от модели; веса навыков словаря не меняются."""
    _model(monkeypatch, net, {"stack_required": [{"tag": "rabbitmq", "weight": 0.4, "quote": "очереди задач"}]})
    monkeypatch.setattr(fast_parse, "_spawn", lambda fn, *a: fn(*a))
    te = employer(client)
    text = "Нужен Python-разработчик: Django, очереди задач, PostgreSQL. Офис в Москве, удалёнка не предусмотрена."
    r = client.post("/api/employer/needs/parse", json={"text": text}, headers=H(te)).json()
    assert r["work_format"] == "office" and r["work_formats"] is None
    job = client.get(f"/api/employer/needs/parse/{r['parse_job']['id']}", headers=H(te)).json()
    assert job["status"] == "done"
    add = next(d for d in job["delta"] if d["kind"] == "add_tag")
    assert add["tag"] == "rabbitmq" and add["weight"] == 0.8  # модель дала 0,4
    assert _w(job["result"]) == {**_w(r), "rabbitmq": 0.8}
    assert r["weight_rule"] == job["result"]["weight_rule"] == ORDER_WEIGHT_RULE
    assert fast_parse.PARSER_VERSION != "fp3"  # правила изменились — старый кэш разбора не отдаётся
