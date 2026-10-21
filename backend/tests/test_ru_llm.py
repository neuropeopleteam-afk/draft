"""Режим «только российская модель» (LLM_CHAIN=yandex) — все четыре LLM-функции идут только в Yandex AI Studio,
ответы в типичном для YandexGPT виде (пояснение + блок ```json) принимаются, вторая оценка — та же модель
независимым вызовом; блок /validation#ru-llm отдаёт сводку замера (backend/app/modules/validation/data/ru_llm.json).

Сеть не используется: транспорт httpx подменён (как в test_llm_chain.py), ответы — фиктивные.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.modules.llm import client as llm
from tests.test_llm_chain import (ANSWER, NEED_TEXT, QUOTES, RUBRIC, SECRET_OR, SECRET_YA, configure, net,  # noqa: F401
                                  reply)

ROOT = Path(__file__).resolve().parents[2]
YA = "yandex=yandexgpt-5.1/latest"
RU = {"LLM_CHAIN": "yandex", "LLM_MODEL_PARSE_NEED": YA, "LLM_MODEL_RESUME": YA, "LLM_MODEL_GRADE": YA,
      "LLM_MODEL_GRADE_SECOND": YA}


def _fenced(obj) -> str:
    """Так YandexGPT часто отвечает: фраза, затем JSON в блоке кода."""
    return "Вот результат разбора:\n```json\n" + json.dumps(obj, ensure_ascii=False, indent=2) + "\n```"


def test_ru_only_routes_every_function_to_yandex(monkeypatch, net, client):
    configure(monkeypatch, **RU)  # ключ OpenRouter тоже задан — в цепочке его нет, значит, и запросов к нему нет
    for f in llm.FUNCTIONS:
        (r,) = llm.routes(f)
        assert (r.provider, r.model) == ("yandex", "gpt://b1folder/yandexgpt-5.1/latest"), f
    j = client.get("/api/meta").json()["llm"]
    assert [c["provider"] for c in j["chain"]] == ["yandex"]
    assert {x["models"][0]["label"] for x in j["functions"].values()} == {"YandexGPT 5.1"}
    assert SECRET_YA not in json.dumps(j) and SECRET_OR not in json.dumps(j) and "b1folder" not in json.dumps(j)


def test_ru_only_need_delta_fenced_reply(monkeypatch, net):
    from app.modules.matching.need_parser import parse_need

    configure(monkeypatch, **RU)
    net.on("ya.test", None, lambda req, body: reply(_fenced({
        "stack_required": [{"tag": "grpc", "weight": 0.7, "quote": "межсервисное взаимодействие"}],
        "stack_desired": [], "confirm": ["python"], "remove": [], "unknown_required": [],
        "direction": None, "grade": None, "experience_years_min": None, "work_format": None,
        "quotes": {"direction": None, "grade": None, "experience_years_min": None, "work_format": None}}), body["model"]))
    r = parse_need(NEED_TEXT)
    assert r["method"] == "llm+rules" and r["llm"]["provider"] == "yandex" and r["llm"]["model_label"] == "языковая модель"
    grpc = next(i for i in r["stack_required"] if i["tag"] == "grpc")
    assert grpc["evidence"]["model"] == "языковая модель"
    (c,) = net.calls
    assert c["host"] == "ya.test" and c["headers"]["authorization"] == f"Api-Key {SECRET_YA}"
    assert "response_format" not in c["body"] and "reasoning" not in c["body"]  # у Yandex — без схемы и рассуждений


def test_ru_only_need_delta_json_schema_flag(monkeypatch, net):
    """LLM_YANDEX_JSON_SCHEMA=true — схема дельты уходит и в Yandex AI Studio; не принял (HTTP 400) — повтор без схемы."""
    from app.modules.matching.need_parser import parse_need

    configure(monkeypatch, **RU, LLM_YANDEX_JSON_SCHEMA="true")
    good = {"stack_required": [{"tag": "grpc", "weight": 0.7, "quote": "межсервисное взаимодействие"}],
            "stack_desired": [], "confirm": [], "remove": [], "unknown_required": []}

    def ya(req, body):
        if "response_format" in body:
            return __import__("httpx").Response(400, json={"error": {"message": "schema not supported"}})
        return reply(json.dumps(good), body["model"])

    net.on("ya.test", None, ya)
    r = parse_need(NEED_TEXT)
    assert r["llm"]["used"] and any(i["tag"] == "grpc" for i in r["stack_required"])
    first, second = net.calls
    assert first["body"]["response_format"]["type"] == "json_schema" and "response_format" not in second["body"]
    net.calls.clear()
    net.on("ya.test", None, lambda req, body: reply(json.dumps(good), body["model"]))  # схема принята — один вызов
    parse_need(NEED_TEXT + " ")
    (c,) = net.calls
    assert c["body"]["response_format"]["json_schema"]["name"] == "need_delta"


def test_ru_only_grade_second_same_model_independent_call(monkeypatch, net):
    from app.modules.assessment.grader import grade_open

    configure(monkeypatch, **RU, LLM_GRADING_SECOND_ASYNC="false")
    near = {"criteria": {k: {"score": v, "quote": QUOTES[k]} for k, v in {"cause": 1, "fix": 0}.items()},
            "level": "medium", "comment": "ок"}  # балл 0,5 — у порога → вторая оценка
    net.on("ya.test", None, lambda req, body: reply(_fenced(near), body["model"]))
    g = grade_open(stem="Найдите ошибку бронирования", code=None, step_prompt=None, rubric=RUBRIC, answer=ANSWER)
    assert g.status == "scored" and g.method == "llm2" and g.score == 0.5 and "near_threshold" in g.checks
    assert g.model_label == "языковая модель" and g.second["model_label"] == "вторая модель"
    first, second = net.calls
    assert {first["host"], second["host"]} == {"ya.test"} and first["model"] == second["model"]
    assert first["body"]["messages"] != second["body"]["messages"]  # второй вызов — обратный порядок, без первой оценки


def test_ru_only_resume_on_yandex(monkeypatch, net):
    from app.modules.resume.extract import extract

    configure(monkeypatch, **RU)
    net.on("ya.test", None, lambda req, body: reply(_fenced(
        {"stack": ["grpc", "kubernetes"], "roles": ["developer"], "soft_skills": [], "experience_years": 4}),
        body["model"]))
    o = extract("[ФИО]\nBackend. Опыт: 4 года. Сервисы на Go, межсервисное взаимодействие, деплой в кубер.")
    assert o["method"] == "llm+rules" and o["llm"]["provider"] == "yandex" and o["llm"]["model_label"] == "языковая модель"
    by_llm = {s["tag"] for s in o["stack"] if s.get("by") == "llm"}
    assert "grpc" in by_llm and "kubernetes" in {x["tag"] for x in o["stack"]} and o["experience_years"] == 4.0
    assert all(c["host"] == "ya.test" for c in net.calls)


def test_ru_only_yandex_down_falls_to_rules(monkeypatch, net):
    """Yandex недоступен — разбор по словарю, оценка «на проверке»; в OpenRouter запросов нет."""
    from app.modules.assessment.grader import grade_open
    from app.modules.matching.need_parser import parse_need

    configure(monkeypatch, **RU)
    net.on("ya.test", None, lambda req, body: reply("К сожалению, я не могу ничего сказать об этом.", body["model"]))
    r = parse_need(NEED_TEXT)
    assert r["llm"]["used"] is False and r["llm"]["reason"] == "invalid_json" and r["stack_required"]
    g = grade_open(stem="Найдите ошибку", code=None, step_prompt=None, rubric=RUBRIC, answer=ANSWER)
    assert g.status == "pending" and g.score is None
    assert net.calls and all(c["host"] == "ya.test" for c in net.calls)


# ------------------------------------------------------------------ блок /validation#ru-llm
def test_api_ru_llm(client):
    d = client.get("/api/validation/ru-llm").json()
    assert not d.get("missing")
    # ключи моделей на экранном API — нейтральные коды (поставщики не называются, validation/no_vendor.py)
    assert [m["key"] for m in d["models"]] == ["stand", "ru", "rules"]
    keys = [f["key"] for f in d["functions"]]
    assert keys == ["needs_delta", "needs_full", "needs_jury", "resume", "grade"]
    for f in d["functions"]:
        assert f["rows"]["stand"]["status"] == "done" and f["rows"]["rules"]["status"] == "done"
        y = f["rows"]["ru"]
        assert y["status"] in ("done", "pending")
        for m in ("stand", "ru"):
            c = f["rows"][m]
            if c["status"] == "done":
                assert c["ok"] <= c["n"] and c["p50_s"] <= c["p95_s"]
    if any(f["rows"]["ru"]["status"] == "pending" for f in d["functions"]):
        assert "ещё не замерена" in d["pending_note"]  # честно: нет прогона — нет числа
    assert d["how_to_enable"]["env"][0] == "LLM_CHAIN=yandex"
    text = " ".join(d["conditions"])
    assert "не экспертная" in text and "модель" in text
    raw = json.dumps(d, ensure_ascii=False)
    assert "Api-Key" not in raw and "sk-or" not in raw and "gpt://" not in raw  # ни ключей, ни каталога Yandex Cloud


def test_ru_llm_docs_table_from_json():
    """Таблица docs/LLM.md, раздел 11 — из того же JSON (не текстом)."""
    import sys

    sys.path.insert(0, str(ROOT / "tools" / "llm"))
    import ru_llm_summary as S

    d = json.loads((ROOT / "backend/app/modules/validation/data/ru_llm.json").read_text(encoding="utf-8"))
    assert S.md_table(d) in (ROOT / "docs/LLM.md").read_text(encoding="utf-8")
