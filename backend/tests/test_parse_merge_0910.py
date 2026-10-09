"""И27, дополнение штаба 09.10: слияние словаря и модели не теряет значения словаря; условия «офис в Москве».

(1) «Опыт работы: не требуется» = 0 (vac-050, <внутренний документ>, «Находки»): прежнее `rules[key] or llm[key]`
считало 0 пустым и брало значение модели. Теперь значение словаря (в т. ч. 0) остаётся, несогласие модели — только
предложение; модель заполняет лишь то, чего словарь не нашёл. Остальные поля (грейд, направление, формат, теги) — как
были. (2) Находка С2 на стенде (<внутренний документ>, выкладка 2, п. 2): «Удалённо или офис в Москве» → только
«Удалённо», офис и Москва потеряны. Проверено на тексте супервизора и на потребности песочницы жюри (jury/seed.py) —
через разбор, фоновую модель, сохранение и условия версии подборки; плюс «мск» как Москва (не «по МСК»).
Сеть не используется: транспорт httpx подменён (tests/test_llm_chain.py).
"""
from __future__ import annotations

import json

from app.modules.jury.seed import NEEDS as JURY_NEEDS
from app.modules.matching import fast_parse
from app.modules.matching.need_parser import parse_conditions, parse_need, parse_rules
from tests.test_day2_rules import H, employer
from tests.test_llm_chain import configure, net, reply  # noqa: F401 — фикстура net

VAC050 = ("# Unity-разработчик\nОпыт работы: не требуется\nФормат работы: на\u00a0месте работодателя\n\n"
          "Ищем junior Unity-разработчика: C#, Git. Обучение внутри команды.")
SUPERVISOR = ("Ищем junior backend-разработчика на Python в команду поддержки: обязательно Python и SQL, желательно Git "
              "и Linux. Удалённо или офис в Москве. 80–120 тыс. ₽ на руки.")  # текст С2 на стенде 09.10 (sup2_shots/b10)
JURY_OFFICE = next(t for t in JURY_NEEDS if "Офис в Москве" in t)  # потребность песочницы жюри с офисом
EMPTY = {"stack_required": [], "stack_desired": [], "confirm": [], "remove": [], "unknown_required": [],
         "direction": None, "grade": None, "experience_years_min": None, "work_format": None,
         "quotes": {"direction": None, "grade": None, "experience_years_min": None, "work_format": None}}


def _model(monkeypatch, net, delta: dict) -> None:
    configure(monkeypatch, LLM_CHAIN="openrouter")
    net.on("or.test", None, lambda req, body: reply(json.dumps({**EMPTY, **delta}, ensure_ascii=False), body["model"]))


def _body(r: dict) -> dict:
    return {k: v for k, v in r.items() if k not in ("method", "bias", "suggested_text", "llm", "salary_net",
                                                     "llm_remove", "llm_suggest", "excluded", "salary_note",
                                                     "coverage", "parse_job", "delta")}


# ------------------------------------------------------------------ (1) опыт 0 не теряется
def test_zero_experience_from_rules_is_not_overwritten_by_model(monkeypatch, net):
    rules = parse_rules(VAC050)
    assert rules["experience_years_min"] == 0.0 and rules["work_format"] == "office"
    _model(monkeypatch, net, {"experience_years_min": 2, "work_format": "remote", "grade": "middle",
                              "stack_required": [{"tag": "docker", "weight": 0.5, "quote": "Обучение внутри команды"}],
                              "quotes": {**EMPTY["quotes"], "experience_years_min": "Unity-разработчика",
                                         "work_format": "на месте работодателя", "grade": "junior Unity"}})
    base = parse_need(VAC050, use_llm=False)  # словарь + ближайшая категория (gamedev → coverage)
    r = parse_need(VAC050)
    assert r["method"] == "llm+rules"
    assert r["experience_years_min"] == 0.0  # было: 2 от модели — «не требуется» потерян
    assert r["evidence"]["experience_years_min"]["source"] == "rules"
    # другие поля словаря тоже остались, модель их не перезаписала
    assert r["work_format"] == rules["work_format"] and r["grade"] == rules["grade"] == "junior"
    assert r["direction"] == base["direction"] and r.get("coverage") == base.get("coverage")
    assert {i["tag"] for i in rules["stack_required"]} <= {i["tag"] for i in r["stack_required"]}
    assert "docker" in {i["tag"] for i in r["stack_required"]}  # новый тег модели с цитатой — добавлен, как раньше
    # несогласие модели с опытом — предложение «от 2 лет вместо 0», не молчаливая замена
    sug = {s["field"]: s for s in r["llm_suggest"]}
    assert sug["experience_years_min"]["value"] == 2 and sug["experience_years_min"]["current"] == 0.0


def test_model_fills_experience_only_when_rules_found_nothing(monkeypatch, net):
    text = "Junior QA-инженер: ручное тестирование, Postman, SQL. Можно без опыта, обучим. Удалённо."
    assert parse_rules(text)["experience_years_min"] is None
    _model(monkeypatch, net, {"experience_years_min": 0,
                              "quotes": {**EMPTY["quotes"], "experience_years_min": "Можно без опыта"}})
    r = parse_need(text)
    assert r["experience_years_min"] == 0.0  # 0 от модели — тоже значение, а не «пусто»
    assert r["evidence"]["experience_years_min"]["source"] == "llm"
    assert r["evidence"]["experience_years_min"]["quote"] == "Можно без опыта"
    assert r["work_format"] == "remote" and r["grade"] == "junior"


def test_fast_job_zero_experience_offer_not_silent(client, monkeypatch, net):
    """Фон (И27): итог задачи сохраняет 0 словаря; модель видна только как предложение (auto=False)."""
    _model(monkeypatch, net, {"experience_years_min": 3,
                              "quotes": {**EMPTY["quotes"], "experience_years_min": "Unity-разработчика"}})
    monkeypatch.setattr(fast_parse, "_spawn", lambda fn, *a: fn(*a))
    t = employer(client)
    r = client.post("/api/employer/needs/parse", json={"text": VAC050}, headers=H(t)).json()
    assert r["experience_years_min"] == 0.0
    j = client.get(f"/api/employer/needs/parse/{r['parse_job']['id']}", headers=H(t)).json()
    assert j["status"] == "done" and j["result"]["experience_years_min"] == 0.0
    kinds = {(d["kind"], d.get("field")): d for d in j["delta"]}
    assert ("set_scalar", "experience_years_min") not in kinds
    assert kinds[("suggest_scalar", "experience_years_min")]["auto"] is False


def test_parser_version_bumped():
    assert fast_parse.PARSER_VERSION != "fp2"  # правила слияния и города изменились — старый кэш не отдаётся


# ------------------------------------------------------------------ (2) «офис в Москве» (С2)
def test_c2_remote_or_moscow_office_kept_through_model_save_and_selection(client, monkeypatch, net):
    t = employer(client)
    for text, first in ((SUPERVISOR, "remote"), (JURY_OFFICE, "office")):
        # модель сужает формат до одного («удалённо») — словарь уже принял несколько, предложение не показывается
        _model(monkeypatch, net, {"work_format": "remote",
                                  "quotes": {**EMPTY["quotes"], "work_format": "удалённо" if first == "office"
                                             else "Удалённо"}})
        r = parse_need(text)
        assert r["work_format"] == first and set(r["work_formats"]) == {"remote", "office", "hybrid"}, text
        assert r["city"] == "Москва" and r["evidence"]["city"]["quote"] == "Москве"
        assert not [s for s in r["llm_suggest"] if s["field"] == "work_format"]
        n = client.post("/api/employer/needs", json={"text": text, "requirements": _body(r)}, headers=H(t))
        assert n.status_code == 201, n.text
        saved = n.json()["requirements"]
        assert saved["city"] == "Москва" and set(saved["work_formats"]) == {"remote", "office", "hybrid"}
        s = client.get(f"/api/employer/needs/{n.json()['id']}/selections/1", headers=H(t)).json()
        assert s["conditions"]["applied"]["city"] == "Москва", s["conditions"]
        assert "office" in s["conditions"]["applied"]["work_formats"]
        assert "Москва" in s["conditions"]["text"] and "офис" in s["conditions"]["text"].lower()


def test_c2_msk_abbreviation_is_moscow_but_not_time_zone():
    for text in ("офис в мск или удалёнка", "удаленно или офис мск", "Гибрид, МСК", "Офис (мск)"):
        assert parse_conditions(text)["city"] == "Москва", text
    assert set(parse_conditions("офис в мск или удалёнка")["work_formats"]) == {"office", "remote", "hybrid"}
    for text in ("Офис, график 10–19 по МСК", "Офис, время МСК", "Офис, с 10 до 19 мск",
                 "Удалённо, часовой пояс МСК±2"):
        assert parse_conditions(text)["city"] is None, text
    assert parse_conditions("Офис в Казани, созвоны по мск")["city"] == "Казань"
    assert parse_conditions("удаленка, мск")["city"] is None  # только удалёнка — город к условию не относится
