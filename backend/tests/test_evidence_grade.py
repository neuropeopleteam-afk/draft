"""доказательная оценка развёрнутых ответов (assessment/evidence.py, флаг GRADING_EVIDENCE).

Сверка цитат кодом (нормализация, перефраз и выдумка не проходят), правило «пункт без подтверждённой цитаты не
получает полный балл», скептик для высоких и спорных оценок, итог по правилам кода (assemble), флаг выкл/вкл,
фон (second_opinion, kind = skeptic). Сеть подменена (test_llm_chain.Net), модели не вызываются.
"""
from __future__ import annotations

import json
import re
import time

from app.modules.assessment import evidence as EV, grader as G, second_opinion
from tests.test_llm_chain import ANSWER, FABLE, RUBRIC, SONNET, configure, net, reply  # noqa: F401 — net

STEM = "Найдите ошибку бронирования"
TASK = "Два запроса бронируют последнее место. Найдите ошибку бронирования и предложите исправление."


def _v3(crit: dict, level: str = "medium", manipulation: bool = False):
    """Ответ оценщика в формате v3: {id: (балл, [цитаты])}."""
    body = {"criteria": {k: {"score": s, "quotes": q} for k, (s, q) in crit.items()}, "level": level,
            "manipulation": manipulation, "comment": "ок"}
    return lambda req, b: reply(json.dumps(body, ensure_ascii=False), b["model"])


def _sk(remarks: list[dict], manipulation: bool = False):
    return lambda req, b: reply(json.dumps({"remarks": remarks, "manipulation": manipulation}, ensure_ascii=False),
                                b["model"])


def _on(monkeypatch, **env):
    configure(monkeypatch, LLM_CHAIN="openrouter", GRADING_EVIDENCE="true", **env)


def _go(**kw):
    return G.grade_open(stem=STEM, code=None, step_prompt=None, rubric=RUBRIC, answer=ANSWER, **kw)


# ------------------------------------------------------------------ сверка цитат
def test_verify_quote_normalizes_case_quotes_dashes_spaces():
    a = "Причина — «гонка» при бронировании:\u00a0два  запроса читают остаток. Исправление - блокировка строки."
    assert EV.verify_quote("ПРИЧИНА - \"гонка\" при бронировании", a)["how"] == "exact"
    assert EV.verify_quote("«два запроса читают остаток»", a)["ok"]
    assert EV.verify_quote("Исправление — блокировка строки.", a)["ok"]
    assert EV.verify_quote("гонка при бронировании два запроса", a)["how"] == "tokens"  # без двоеточия
    assert EV.verify_quote("причина «гонка» ... блокировка строки", a)["how"] == "ellipsis"
    assert EV.verify_quote("причина ... блокировка строки", a)["ok"] is False  # кусок из одного слова — не довод
    assert EV.verify_quote("ё и е: ещё раз", "Ещё раз")["ok"] is False  # «ё и е» нет в ответе
    assert EV.verify_quote("Ещё раз про блокировку", "ещё раз про блокировку строк")["ok"]


def test_verify_quote_rejects_paraphrase_invented_and_short():
    a = ANSWER
    assert EV.verify_quote("гонка данных при одновременной записи", a) == {"ok": False, "how": None,
                                                                         "why": "not_found"}
    assert EV.verify_quote("используется SELECT FOR UPDATE и уровень SERIALIZABLE", a)["why"] == "not_found"
    # нечёткого совпадения нет: склейка без многоточия, обратный порядок, пропуск или замена слова — не дословно
    assert EV.verify_quote("читают остаток одновременно блокировка строки", a)["why"] == "not_found"
    assert EV.verify_quote("блокировка строки два запроса читают остаток", a)["why"] == "not_found"
    assert EV.verify_quote("два запроса не читают остаток одновременно", a)["why"] == "not_found"  # смысл обратный
    long_a = "Итак, функция `daily_revenue` должна принять три параметра: `orders`, `day` и `timezone`."
    assert EV.verify_quote("функция должна принять три параметра: orders, day и timezone", long_a)["ok"] is False
    assert EV.verify_quote("функция … должна принять три параметра: orders, day и timezone", long_a)["ok"] is False
    assert EV.verify_quote("должна принять три параметра: orders, day и timezone", long_a)["how"] == "tokens"
    assert EV.verify_quote("метод обязан принять три параметра: orders, day и timezone", long_a)["ok"] is False
    assert EV.verify_quote("блокировка … идемпотентность ключа", a)["why"] == "not_found"  # часть не из ответа
    assert EV.verify_quote("гонка", a)["why"] == "too_short"
    assert EV.verify_quote("", a)["why"] == "too_short"
    echo = "Два запроса бронируют последнее место. Найдите ошибку бронирования и предложите исправление. Не знаю."
    v = EV.verify_quote("два запроса бронируют последнее место найдите ошибку", echo, TASK)
    assert v["ok"] is False and v["why"] == "from_task"
    assert EV.verify_quote("последнее место", echo, TASK)["ok"]  # короткий фрагмент условия — можно


def test_full_score_needs_verified_quote():
    raw = {"cause": {"score": 1, "quotes": ["гонка данных при одновременной записи", "два запроса читают остаток"]},
           "fix": {"score": 1, "quotes": ["используется SELECT FOR UPDATE"]}}
    ev = EV.verify_criteria(raw, {"cause": 1.0, "fix": 1.0}, RUBRIC, ANSWER)
    assert ev["scores"] == {"cause": 1.0, "fix": 0.5}  # без подтверждённой цитаты — на шаг ниже
    assert ev["capped"] == ["fix"] and ev["dropped_total"] == 2 and ev["quotes_total"] == 3
    c = ev["criteria"]
    assert [q["text"] for q in c["cause"]["quotes"]] == ["два запроса читают остаток"]
    assert c["cause"]["dropped"] == [{"text": "гонка данных при одновременной записи", "why": "not_found"}]
    assert c["fix"]["capped"] and c["fix"]["model_score"] == 1.0 and c["fix"]["quotes"] == []
    half = EV.verify_criteria({"cause": {"score": 0.5}, "fix": 0}, {"cause": 0.5, "fix": 0.0}, RUBRIC, ANSWER)
    assert half["scores"] == {"cause": 0.0, "fix": 0.0} and half["no_quotes"] and half["capped"] == ["cause"]
    v2 = EV.verify_criteria({"cause": {"score": 1, "quote": "два запроса читают остаток"}, "fix": {"score": 0}},
                            {"cause": 1.0, "fix": 0.0}, RUBRIC, ANSWER)
    assert v2["scores"]["cause"] == 1.0 and not v2["capped"]  # формат v2 (одна quote) тоже понимается


def test_parse_reply_v3_and_v2_unchanged():
    data = {"criteria": {"cause": {"score": 1, "quotes": ["два запроса читают остаток одновременно"]},
                         "fix": {"score": 1, "quotes": ["исправление — транзакция SERIALIZABLE"]}}, "level": "strong"}
    p = G.parse_reply(data, RUBRIC, ANSWER, version="v3", task_text=TASK)
    assert p["ok"] and p["criteria"] == {"cause": 1.0, "fix": 0.5} and p["score"] == 0.75
    assert p["unsupported"] == ["fix"] and p["evidence"]["capped"] == ["fix"] and p["evidence"]["rule"] == "step_down"
    assert p["quotes"] == {"cause": "два запроса читают остаток одновременно"}
    v2 = {"criteria": {k: {"score": v["score"], "quote": v["quotes"][0]} for k, v in data["criteria"].items()}}
    p2 = G.parse_reply(v2, RUBRIC, ANSWER)  # флаг выключен — прежнее правило v2 (нечёткое совпадение, обнуление)
    assert p2["evidence"] is None and p2["criteria"]["fix"] == 0.0


# ------------------------------------------------------------------ пробы независимой проверки (10.10): отрицание и цитата без доказательства
Y5_RUBRIC = {"criteria": [{"id": "x", "weight": 1, "description": "Решение о данных"}]}
Y5_ANSWER = "данные следует удалять"


def test_y5_negation_probes_flag_off_v2():
    assert G.quote_supported("данные не следует удалять", Y5_ANSWER) is False  # было True: «не» короче 3 букв
    assert G.quote_supported("данные следует удалять", "данные не следует удалять") is False  # «не» потеряно
    assert G.quote_supported("следует удалять", "данные не следует удалять") is False
    assert G.quote_supported("не следует удалять", "мне следует удалять данные") is False  # целыми словами
    assert G.quote_supported("данные следует удалять", Y5_ANSWER)
    assert G.quote_supported("сначала не удалять, потом удалить", "Сначала не удалять, а потом удалить.")
    p = G.parse_reply({"criteria": {"x": {"score": 1, "quote": "данные не следует удалять"}}}, Y5_RUBRIC, Y5_ANSWER)
    assert p["ok"] and p["score"] == 0.0 and p["unsupported"] == ["x"]
    # число без цитаты при выключенном флаге — прежнее правило: балл не снижается, но это причина сомнения (вторая
    # оценка); «без подтверждённой цитаты — не полный балл» — под GRADING_EVIDENCE (решение 10.10, до замера)
    p = G.parse_reply({"criteria": {"x": 1}}, Y5_RUBRIC, Y5_ANSWER)
    assert p["ok"] and p["score"] == 1.0 and p["no_quotes"] and "no_quotes" in G.doubts(p, Y5_ANSWER, 5)
    a = "Нет: в READ COMMITTED каждый SELECT видит данные. Не следует удалять данные."
    assert G.quote_supported("в READ COMMITTED каждый SELECT видит данные", a)  # «Нет:» — ответ, не отрицание
    assert G.quote_supported("не следует удалять данные", a)
    assert G.quote_supported("следует удалять данные", a) is False


def test_y5_negation_probes_flag_on_v3():
    v = EV.verify_quote("данные не следует удалять", Y5_ANSWER)
    assert v == {"ok": False, "how": None, "why": "not_found"}
    assert EV.verify_quote("данные следует удалять", "данные не следует удалять")["why"] == "not_found"
    assert EV.verify_quote("следует удалять", "данные не следует удалять") == {"ok": False, "how": None,
                                                                             "why": "negation"}
    assert EV.verify_quote("следует удалять", "Не следует хранить. Следует удалять сразу.")["ok"]  # есть без «не»
    assert EV.verify_quote("удалять следует данные", Y5_ANSWER)["why"] == "not_found"  # порядок слов
    a = "Нет: в READ COMMITTED каждый SELECT видит данные. Варианты: SELECT ... FROM events WHERE id = $1 FOR UPDATE."
    assert EV.verify_quote("в READ COMMITTED каждый SELECT видит данные", a)["ok"]  # «Нет:» — ответ на вопрос
    assert EV.verify_quote("SELECT … FROM events WHERE id = $1 FOR UPDATE", a)["how"] == "tokens"  # «…» из кода
    code = "При открытии файла — флаг O_NOFOLLOW (в Python open(..., opener=…) или os.open)."
    assert EV.verify_quote("флаг O_NOFOLLOW (в Python open(..., opener=…) или os.open)", code)["ok"]
    assert EV.verify_quote("не следует удалять", "мне следует удалять данные")["why"] == "not_found"
    assert EV.verify_quote("исправление здесь … блокировка строки",
                           "Исправление здесь — не блокировка строки, а очередь.")["why"] == "negation"
    for reply in ({"x": {"score": 1, "quotes": ["данные не следует удалять"]}}, {"x": 1}):
        p = G.parse_reply({"criteria": reply}, Y5_RUBRIC, Y5_ANSWER, version="v3")
        assert p["ok"] and p["score"] == 0.5 and p["unsupported"] == ["x"]  # без доказательства — не полный балл
    p = G.parse_reply({"criteria": {"x": {"score": 1, "quotes": ["данные следует удалять"]}}}, Y5_RUBRIC, Y5_ANSWER,
                      version="v3")
    assert p["score"] == 1.0


def test_spans_point_to_original_answer():
    a = "Причина —\u00a0«Гонка»: ДВА  запроса читают остаток. Ёлка ещё растёт."
    for q in ("два запроса читают остаток", "«гонка» два запроса", "елка еще растет", "причина гонка … читают остаток"):
        v = EV.verify_quote(q, a)
        assert v["ok"], q
        assert EV.tokens(" ".join(a[s:e] for s, e in v["spans"])) == EV.tokens(q), q
    assert EV.verify_quote("«Гонка»: ДВА запроса", a)["how"] == "exact"


def test_no_evidence_or_invalid_output_goes_to_expert(monkeypatch, net):
    _on(monkeypatch)
    net.on("or.test", SONNET, lambda req, b: reply(json.dumps({"criteria": {"cause": 1, "fix": 1}}), b["model"]))
    net.on("or.test", FABLE, lambda req, b: reply("не JSON", b["model"]))
    g = _go()  # числа без цитат: на шаг ниже, причина сомнения, скептик не ответил → эксперт
    assert g.status == "pending" and g.score is None and g.error == "second_opinion_failed"
    assert "no_quotes" in g.checks and g.criteria == {"cause": 0.5, "fix": 0.5}
    net.on("or.test", SONNET, lambda req, b: reply("не JSON", b["model"]))
    g = _go()
    assert g.status == "pending" and g.score is None and g.error


# ------------------------------------------------------------------ флаг
def test_flag_off_keeps_v2_prompt(monkeypatch, net):
    configure(monkeypatch, LLM_CHAIN="openrouter")
    net.on("or.test", SONNET, lambda req, b: reply(json.dumps({"criteria": {
        "cause": {"score": 1, "quote": "два запроса читают остаток"}, "fix": {"score": 1, "quote": "блокировка строки"}},
        "level": "strong", "comment": "ок"}), b["model"]))
    g = _go(second_async=True)
    assert g.prompt == "v2" and g.evidence is None and g.second is None and g.score == 1.0
    assert '"quote": "цитата"' in net.calls[0]["body"]["messages"][0]["content"]


def test_flag_on_v3_prompt_evidence_and_async_skeptic(monkeypatch, net):
    _on(monkeypatch)
    net.on("or.test", SONNET, _v3({"cause": (1, ["два запроса читают остаток одновременно"]),
                                   "fix": (1, ["блокировка строки", "транзакция SERIALIZABLE решает всё"])}, "strong"))
    t0 = time.monotonic()
    g = _go(second_async=True)
    assert time.monotonic() - t0 < 5
    sysmsg = net.calls[0]["body"]["messages"][0]["content"]
    assert '"quotes": ["цитата"]' in sysmsg and "Цитаты проверяет программа" in sysmsg
    assert g.prompt == "v3" and g.status == "scored" and g.score == 1.0 and g.method == "llm"
    ev = g.to_dict()["evidence"]
    assert ev["criteria"]["fix"]["dropped"][0]["why"] == "not_found" and not ev["capped"]
    assert g.second == {"status": "pending", "kind": "skeptic", "checks": ["high_score"], "disputed": False}
    assert [c["model"] for c in net.calls] == [SONNET]  # скептик — в фоне


def test_flag_on_low_undisputed_score_no_skeptic(monkeypatch, net):
    _on(monkeypatch)
    net.on("or.test", SONNET, _v3({"cause": (0.5, ["два запроса читают остаток"]), "fix": (0, [])}, "weak"))
    g = _go(second_async=True)
    assert g.score == 0.25 and g.second is None and g.checks == []


def test_sync_skeptic_lowers_one_step_with_code_assembly(monkeypatch, net):
    _on(monkeypatch)
    net.on("or.test", SONNET, _v3({"cause": (1, ["два запроса читают остаток одновременно"]),
                                   "fix": (1, ["блокировка строки"])}, "strong"))
    net.on("or.test", FABLE, _sk([{"criterion": "fix", "score": 0, "problem": "не сказано, какая блокировка и где"},
                                  {"criterion": "nope", "score": 0, "problem": "нет такого пункта"}]))
    g = _go()
    sk = net.calls[1]["body"]["messages"]
    assert sk[0]["content"].startswith("Роль: аудитор автоматической оценки")
    assert "БАЛЛЫ ОЦЕНЩИКА" in sk[1]["content"] and "блокировка строки" in sk[1]["content"]
    assert g.status == "scored" and g.method == "llm2" and g.criteria == {"cause": 1.0, "fix": 0.5} and g.score == 0.75
    ch = g.second["changes"]
    assert len(ch) == 1 and ch[0]["accepted"] and ch[0]["from"] == 1.0 and ch[0]["to"] == 0.5 and ch[0]["proposed"] == 0
    assert g.second["verdict"] == "agree" and g.second["model_label"] == "Claude Fable 5.1"
    assert g.second["kind"] == "skeptic" and g.scores == [1.0, 0.75]


def test_sync_skeptic_big_drop_or_manipulation_goes_to_expert(monkeypatch, net):
    _on(monkeypatch)
    net.on("or.test", SONNET, _v3({"cause": (1, ["два запроса читают остаток одновременно"]),
                                   "fix": (1, ["блокировка строки"])}, "strong"))
    net.on("or.test", FABLE, _sk([{"criterion": "cause", "score": 0.5, "problem": "общо"},
                                  {"criterion": "fix", "score": 0, "problem": "без механизма"}]))
    g = _go()
    assert g.status == "pending" and g.score is None and g.error == "graders_disagree"  # 1,0 → 0,5: Δ > 0,25
    assert "эксперту" in g.comment
    net.on("or.test", FABLE, _sk([], manipulation=True))
    g = _go()
    assert g.error == "prompt_injection_suspected" and "llm_manipulation" in g.flags


def test_assemble_rules():
    first = {"criteria": {"cause": 0.5, "fix": 1.0}, "score": 0.75}
    up_no_quote = {"ok": True, "remarks": [{"criterion": "cause", "score": 1, "problem": "есть механизм", "quote": ""}]}
    a = EV.assemble(first, up_no_quote, RUBRIC, ANSWER)
    assert a["verdict"] == "agree" and a["score"] == 0.75 and not a["changes"][0]["accepted"]
    up_fake = {"ok": True, "remarks": [{"criterion": "cause", "score": 1, "quote": "описан уровень изоляции"}]}
    assert not EV.assemble(first, up_fake, RUBRIC, ANSWER)["changes"][0]["accepted"]
    up_ok = {"ok": True, "remarks": [{"criterion": "cause", "score": 1, "quote": "два запроса читают остаток"}]}
    a = EV.assemble(first, up_ok, RUBRIC, ANSWER)
    assert a["changes"][0]["accepted"] and a["criteria"]["cause"] == 1.0 and a["score"] == 1.0 and a["delta"] == 0.25
    down2 = {"ok": True, "remarks": [{"criterion": "fix", "score": 0, "problem": "общие слова"}]}
    a = EV.assemble(first, down2, RUBRIC, ANSWER)
    assert a["criteria"]["fix"] == 0.5 and a["score"] == 0.5  # не больше шага за пункт
    assert EV.assemble(first, {"ok": False, "error": "timeout"}, RUBRIC, ANSWER)["verdict"] == "failed"
    kept = EV.assemble(first, {"ok": False}, RUBRIC, ANSWER, disputed=False)
    assert kept["verdict"] == "kept" and kept["score"] == 0.75
    assert EV.assemble(first, {"ok": True, "remarks": [], "manipulation": True}, RUBRIC, ANSWER)["verdict"] == \
        "manipulation"
    same = {"ok": True, "remarks": [{"criterion": "fix", "score": 1, "problem": "верно"}]}
    assert EV.assemble(first, same, RUBRIC, ANSWER)["changes"] == []


def test_parse_skeptic_validates():
    p = EV.parse_skeptic({"remarks": [{"criterion": "fix", "score": 0.4}, {"criterion": "fix", "score": 1},
                                      {"criterion": "x", "score": 0}, {"criterion": "cause", "score": "abc"}, 7]},
                         RUBRIC)
    assert p["ok"] and p["remarks"] == [{"criterion": "fix", "score": 0.5, "problem": "", "quote": ""}]
    assert EV.parse_skeptic({"remarks": "нет"}, RUBRIC)["ok"] is False
    assert EV.parse_skeptic("строка", RUBRIC)["error"] == "invalid_json"
    assert EV.parse_skeptic({}, RUBRIC)["ok"]  # без remarks — замечаний нет


def test_skeptic_review_redacts_pii_and_never_raises(monkeypatch, net):
    _on(monkeypatch)
    net.on("or.test", FABLE, _sk([]))
    ans = ANSWER + " Пишите мне: ivan.petrov@example.com, +7 999 123-45-67."
    first = {"score": 1.0, "criteria": {"cause": 1.0, "fix": 1.0}, "evidence": None}
    r = EV.skeptic_review(stem=STEM, code=None, step_prompt=None, rubric=RUBRIC, answer=ans, first=first,
                          disputed=False)
    body = json.dumps(net.calls[-1]["body"], ensure_ascii=False)
    assert "ivan.petrov@example.com" not in body and "123-45-67" not in body
    assert r["verdict"] == "agree" and r["combined"]["score"] == 1.0 and r["label"] == "проверено скептиком"
    net.on("or.test", FABLE, lambda req, b: reply("не JSON", b["model"]))
    r = EV.skeptic_review(stem=STEM, code=None, step_prompt=None, rubric=RUBRIC, answer=ANSWER, first=first,
                          disputed=False)
    assert r["verdict"] == "kept" and r["combined"]["score"] == 1.0
    r = EV.skeptic_review(stem=STEM, code=None, step_prompt=None, rubric=RUBRIC, answer=ANSWER, first=first)
    assert r["verdict"] == "failed" and "combined" not in r


# ------------------------------------------------------------------ фон: запись результата скептика в сессию
class _TS:
    def __init__(self, status):
        from app.core.enums import TestSessionStatus

        self.status = getattr(TestSessionStatus, status)
        g = {"status": "scored", "method": "llm", "score": 1.0, "criteria": {"cause": 1.0, "fix": 1.0},
             "second": {"status": "pending", "kind": "skeptic", "checks": ["high_score"], "disputed": False}}
        self.result = {"state": {"items": [{"token": "t1", "x": [1.0], "grading": [g], "answers": {}}]}}


def _res(verdict, changes=True):
    r = {"status": "done", "kind": "skeptic", "label": EV.SKEPTIC_LABEL, "verdict": verdict, "score": 0.75,
         "criteria": {"cause": 1.0, "fix": 0.5}, "changes": [{"criterion": "fix"}] if changes else []}
    if verdict in ("agree", "kept"):
        r["combined"] = {"score": 0.75 if changes else 1.0, "criteria": r["criteria"]}
    return r


def test_apply_skeptic_in_progress_and_after_finish(monkeypatch):
    monkeypatch.setattr(second_opinion, "flag_modified", lambda *a: None)
    ts = _TS("in_progress")
    assert second_opinion.apply(ts, "t1", 0, _res("agree"))
    it = ts.result["state"]["items"][0]
    assert it["x"] == [0.75] and it["grading"][0]["method"] == "llm2" and it["grading"][0]["second"]["verdict"] == "agree"
    ts = _TS("in_progress")
    second_opinion.apply(ts, "t1", 0, _res("kept", changes=False))
    assert ts.result["state"]["items"][0]["x"] == [1.0]  # скептик не ответил — первая оценка
    ts = _TS("in_progress")
    second_opinion.apply(ts, "t1", 0, _res("disagree"))
    g = ts.result["state"]["items"][0]["grading"][0]
    assert ts.result["state"]["items"][0]["x"] == [None] and g["error"] == "graders_disagree" and "Скептик" in g["comment"]
    ts = _TS("finished")
    second_opinion.apply(ts, "t1", 0, _res("disagree"))
    g = ts.result["state"]["items"][0]["grading"][0]
    assert ts.result["state"]["items"][0]["x"] == [1.0] and g["disputed"] and g["second"]["after_finish"]
    assert second_opinion.summary(ts.result["state"]) == {"pending": 0, "revised": 1, "disputed": 1, "lost": 0}
    ts = _TS("finished")
    second_opinion.apply(ts, "t1", 0, _res("kept", changes=False))
    assert second_opinion.summary(ts.result["state"])["disputed"] == 0


def test_run_dispatches_skeptic(monkeypatch):
    called = {}

    def fake_review(**kw):
        called.update(kw)
        return _res("agree")

    monkeypatch.setattr(EV, "skeptic_review", fake_review)
    monkeypatch.setattr(G, "second_opinion", lambda **kw: (_ for _ in ()).throw(AssertionError("не та проверка")))
    ts = _TS("in_progress")
    it, g = second_opinion._find(ts.result["state"], "t1", 0)
    it.update(public={"stem": STEM, "code": None, "steps": []}, rubric=RUBRIC, format="open_answer",
              answers={"1": {"value": ANSWER}})

    class DB:
        def get(self, *a):
            return ts

        def rollback(self):
            pass

        def scalar(self, *a):
            return ts

        def commit(self):
            called["commit"] = True

        def close(self):
            pass

    import app.core.db as dbm
    from app.modules.assessment import service

    monkeypatch.setattr(dbm, "SessionLocal", lambda: DB())
    monkeypatch.setattr(service, "_drain_outbox", lambda db, t: None)
    monkeypatch.setattr(second_opinion, "flag_modified", lambda *a: None)
    second_opinion.run("sid", "t1", 0)
    assert called["answer"] == ANSWER and called["disputed"] is False and called["first"]["score"] == 1.0
    assert called.get("commit") and it["x"] == [0.75]


# ------------------------------------------------------------------ API: кандидат, работодатель, /validation (п. 3)
def _inject_evidence(email: str) -> str:
    """Добавляет в последний завершённый тест кандидата развёрнутый ответ, оценённый с цитатами (флаг вкл)."""
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified

    from app.core.db import SessionLocal
    from app.modules.assessment.models import TestSession
    from app.modules.auth.models import User

    p = G.parse_reply({"criteria": {"cause": {"score": 1, "quotes": ["два запроса читают остаток одновременно",
                                                                    "выдуманная цитата про очередь сообщений"]},
                                    "fix": {"score": 1, "quotes": ["транзакция SERIALIZABLE решает всё"]}},
                       "level": "strong"}, RUBRIC, ANSWER, version="v3")
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == email))
        ts = db.scalars(select(TestSession).where(TestSession.user_id == uid)
                        .order_by(TestSession.created_at.desc())).first()
        res = dict(ts.result or {})
        state = dict(res.get("state") or {})
        state["items"] = [*(state.get("items") or []), {
            "token": "ev1", "position": 7, "parts": 1, "skills": ["python", "postgresql"], "rubric": RUBRIC,
            "public": {"stem": "СЕКРЕТНОЕ УСЛОВИЕ", "code": None, "steps": []}, "x": [p["score"]],
            "grading": [{"status": "scored", "method": "llm2", "score": p["score"], "criteria": p["criteria"],
                         "evidence": p["evidence"], "model_label": "Claude Sonnet 5.5",
                         "second": {"status": "done", "kind": "skeptic", "verdict": "agree",
                                    "model_label": "Claude Fable 5.1",
                                    "changes": [{"criterion": "fix", "from": 0.5, "to": 0.0, "accepted": True,
                                                 "direction": "down"}]}}]}]
        res["state"] = state
        ts.result = res
        flag_modified(ts, "result")
        db.commit()
        return str(ts.id)


def test_evidence_api_candidate_employer_validation(client):
    from tests.test_day2_rules import H, candidate_with_category, employer, my_ref

    tc = candidate_with_category(client, email="ev-cand@example.com")
    # фраза о цитатах перед тестом — только при флаге (по умолчанию выключен)
    assert client.get("/api/assessment/status", headers=H(tc)).json()["evidence_grading"] is False
    sid = _inject_evidence("ev-cand@example.com")
    r = client.get(f"/api/assessment/sessions/{sid}/evidence", headers=H(tc))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["title"] == "Доказательства: цитаты из ответа" and d["label"] == "оценка модели" and d["enabled"] is False
    (it,) = d["items"]
    assert it["position"] == 7 and it["method_title"] == "оценка модели, проверено скептиком"
    c1, c2 = it["criteria"]
    assert c1["title"] == "Пункт 1" and c1["quotes"][0]["text"] == "два запроса читают остаток одновременно"
    assert c1["dropped"] == 1 and c1["score"] == 1.0 and not c1["capped"]
    assert c2["capped"] and c2["quotes"] == [] and c2["score"] == 0.5 and c2["dropped_why"] == ["нет в ответе дословно"]
    assert it["skeptic"]["changes"] == [{"n": 2, "from": 0.5, "to": 0.0, "accepted": True, "direction": "down"}]
    body = json.dumps(d, ensure_ascii=False)  # закрытое: условие, тексты пунктов рубрики, эталоны
    assert "СЕКРЕТНОЕ" not in body and "Названа причина" not in body and "ЭТАЛОН" not in body
    other = candidate_with_category(client, email="ev-other@example.com")
    assert client.get(f"/api/assessment/sessions/{sid}/evidence", headers=H(other)).status_code == 404
    assert client.get(f"/api/assessment/sessions/{sid}/evidence").status_code == 401
    # работодатель: последний тест, согласие кандидата (privacy.show_evidence), роли
    te = employer(client, email="ev-hr@corp.ru")
    ref = my_ref(client, tc)
    d = client.get(f"/api/employer/candidates/{ref}/evidence", headers=H(te)).json()
    assert d["available"] and d["items"][0]["criteria"][0]["quotes"] and "СЕКРЕТНОЕ" not in str(d)
    assert "Тексты заданий и рубрик закрыты" in d["note"]
    opts = client.get("/api/me/onboarding", headers=H(tc)).json()["options"]["privacy_fields"]
    assert {"id": "show_evidence", "title": "Цитаты из ответов теста (доказательства оценки)"} in opts
    assert client.put("/api/me/privacy", json={"privacy": {"show_evidence": False}}, headers=H(tc)).status_code == 200
    d = client.get(f"/api/employer/candidates/{ref}/evidence", headers=H(te)).json()
    assert d == {"available": False, "reason": "hidden_by_candidate", "items": [],
                 "text": "Кандидат скрыл цитаты из ответов теста"}
    assert client.get(f"/api/employer/candidates/{ref}/evidence", headers=H(tc)).status_code == 403
    assert client.get(f"/api/employer/candidates/nope/evidence", headers=H(te)).status_code == 404
    # /validation: сводка замера (открыто)
    v = client.get("/api/validation/evidence").json()
    assert v["enabled"] is False and len(v["rows"]) >= 3 and v["default_path_fix"]["changed"] == 0
    # полный прогон 406 (если посчитан): решение — по правилу «не хуже», без номеров исполнителей в открытом тексте
    if v.get("full"):
        assert v["full"]["n"] == 406 and isinstance(v["full"]["decision"]["non_inferior"], bool)
        assert v["full"]["decision"]["text"] in v["decision"]
        assert not re.search("\u042f\\d", json.dumps(v, ensure_ascii=False))  # «Я» и цифра — номер исполнителя
    assert "модели, не люди" in v["world"]


def test_evidence_view_skeptic_raised_criterion_shows_its_quote():
    """Пункт, который скептик повысил с цитатой, подтверждённой кодом, показывает эту цитату и не помечается «без
    подтверждённой цитаты»; у пункта, сниженного правилом, — балл после правила (cap_score), а не итог скептика."""
    from app.modules.assessment import evidence_view as V

    p = G.parse_reply({"criteria": {"cause": {"score": 1, "quotes": ["выдуманная цитата про очередь сообщений"]},
                                    "fix": {"score": 1, "quotes": ["выдумка про индекс"]}}, "level": "strong"},
                      RUBRIC, ANSWER, version="v3")
    assert p["evidence"]["capped"] == ["cause", "fix"]
    sk = EV.assemble({"criteria": p["criteria"], "score": p["score"]},
                     {"ok": True, "manipulation": False,
                      "remarks": [{"criterion": "cause", "score": 1.0, "quote": "два запроса читают остаток одновременно"},
                                  {"criterion": "fix", "score": 0.0, "problem": "исправления нет"}]},
                     RUBRIC, ANSWER, disputed=True)
    assert sk["verdict"] == "agree" and sk["criteria"] == {"cause": 1.0, "fix": 0.0}
    state = {"items": [{"position": 3, "parts": 1, "skills": ["sql"], "rubric": RUBRIC, "x": [sk["score"]],
                        "grading": [{"status": "scored", "method": "llm2", "score": sk["score"], "criteria": sk["criteria"],
                                     "evidence": p["evidence"], "second": {"status": "done", "kind": "skeptic",
                                                                           "verdict": "agree", "changes": sk["changes"]}}]}]}
    (it,) = V.items_view(state)
    c1, c2 = it["criteria"]
    assert c1["score"] == 1.0 and not c1["capped"]
    assert c1["quotes"] == [{"text": "два запроса читают остаток одновременно", "how": "skeptic"}]
    assert c2["capped"] and c2["cap_score"] == 0.5 and c2["score"] == 0.0 and c2["quotes"] == []
    # скептик не согласился (ответ у эксперта) — его цитата не показывается
    state["items"][0]["grading"][0]["second"]["verdict"] = "disagree"
    (it,) = V.items_view(state)
    assert it["criteria"][0]["quotes"] == [] and it["criteria"][0]["capped"]


def test_status_evidence_grading_follows_flag(client, monkeypatch):
    from app.core.config import get_settings
    from tests.test_day2_rules import H, candidate_with_category

    tc = candidate_with_category(client, email="ev-flag@example.com")
    monkeypatch.setenv("GRADING_EVIDENCE", "true")
    get_settings.cache_clear()
    try:
        assert client.get("/api/assessment/status", headers=H(tc)).json()["evidence_grading"] is True
    finally:
        monkeypatch.delenv("GRADING_EVIDENCE", raising=False)
        get_settings.cache_clear()
