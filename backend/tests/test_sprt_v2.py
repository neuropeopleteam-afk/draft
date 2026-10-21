"""Поправка №2 (А4, 21.10 вечер): решение по заявленному грейду — SPRT у его порога по ответам (без априорного
стягивания), продление у спорного порога, второй этап — продолжение того же SPRT, устная защита вместо «монетки»,
отбор заданий у порога по информации 3PL на минуту, квота практических заданий, «уровень по ответам» (WLE).
Проверки — через настоящий движок банка (BankEngine) и сквозной путь API (start → next → answer → finish → verdict)."""
import json
import math
import uuid

import numpy as np
import pytest

from app.core.db import SessionLocal
from app.modules.assessment import bank_engine as be
from app.modules.assessment import sprt as sp
from app.modules.assessment.bank_engine import BankEngine
from app.modules.assessment.grader import GradeOutcome
from tests.conftest import register_and_verify
from tests.test_bank_engine import oracle
from tests.test_day2_rules import ONBOARDING, H

CUT = {"intern": -1.75, "junior": -1.0, "middle": 0.0, "senior": 1.0}


@pytest.fixture
def stand(monkeypatch):
    """Профиль стенда (STAND_ENV симуляции продукта) + правило поправки №2."""
    from app.core.config import get_settings

    s = get_settings()
    for k, v in {"assessment_verdict_rule": "sprt", "assessment_guessing_3pl": True, "assessment_max_items": 20,
                 "assessment_code_quota_ext": True, "assessment_two_stage_enabled": True,
                 "assessment_contested_max_items": 30, "assessment_contested_max_minutes": 90}.items():
        monkeypatch.setattr(s, k, v)
    monkeypatch.setattr(be, "grade_open", lambda **kw: GradeOutcome(
        status="scored", score=0.9 if len(kw.get("answer") or "") > 40 else 0.0, method="llm", model="test"))
    return s


class _Clock:
    """Часы движка (только модуль bank_engine): каждое обращение — +30 с, как у человека, отвечающего не мгновенно
    (иначе срабатывают сигналы «слишком быстро» античита и попытка уходит на устную защиту)."""

    def __init__(self):
        import time as _t

        self.t = _t.time()

    def time(self):
        self.t += 30.0
        return self.t


def play(engine: BankEngine, st: dict, policy) -> None:
    """Кандидат отвечает по политике policy(it) → True (знает) / False."""
    import time as _t

    be.time = _Clock()
    try:
        while (item := engine.next_item(st)) is not None:
            it = next(i for i in st["items"] if i["token"] == item.item_id)
            fb = engine.answer(st, item.item_id, oracle(it, item.step or 1, policy(it)), 60000, step=item.step)
            assert fb.accepted
            assert len(st["items"]) < 60, "сессия не останавливается"
    finally:
        be.time = _t


# ---------------------------------------------------------------- функции правила

def test_bounds_and_status():
    up, lo = sp.sprt_bounds(0.05, 0.10)
    assert math.isclose(up, math.log(0.9 / 0.05)) and math.isclose(lo, math.log(0.1 / 0.95))
    assert sp.sprt_status(up + 0.01, 0.05, 0.10) == "confirmed"
    assert sp.sprt_status(lo - 0.01, 0.05, 0.10) == "not_confirmed"
    assert sp.sprt_status(0.0, 0.05, 0.10) == "needs_followup"


def test_llr_signs_and_guessing():
    # верный ответ — за «выше порога», неверный — против; угадывание уменьшает вклад верного ответа
    assert sp.llr3([1], [1.3], [0.0], [0.0], 0.0, 0.35) > 0 > sp.llr3([0], [1.3], [0.0], [0.0], 0.0, 0.35)
    assert sp.llr3([1], [1.0], [0.0], [0.25], 0.0, 0.35) < sp.llr3([1], [1.0], [0.0], [0.0], 0.0, 0.35)
    assert list(sp.guess_parts("mcq_concept", 1, [5])) == [0.2]
    assert list(sp.guess_parts("open_book_3step", 3, [4, 3, 0])) == [0.25, 1 / 3, 0.0]
    assert math.isclose(float(sp.guess_parts("find_bug", 1, None, 12)[0]), 1 / 12)
    assert list(sp.guess_parts("predict_output", 1)) == [0.0]


def test_wle_finite_monotone_no_prior():
    a, b, c = [1.3] * 8, list(np.linspace(-1, 1, 8)), [0.0] * 8
    lo, _ = sp.wle([0] * 8, a, b, c)
    mid, _ = sp.wle([1, 0] * 4, a, b, c)
    hi, se = sp.wle([1] * 8, a, b, c)
    assert np.isfinite(lo) and np.isfinite(hi) and lo < mid < hi and se > 0
    # без априорного: у Стажёра (порог −1,75) нет стягивания к 0 — все неверные дают оценку ниже −1,75
    assert sp.wle([0] * 8, [1.3] * 8, [-1.6] * 8, [0.0] * 8)[0] < -1.75


def test_product_grade_follows_verdict():
    order = ("intern", "junior", "middle", "senior")
    assert sp.product_grade("confirmed", "junior", "middle", order) == "middle"
    assert sp.product_grade("confirmed", "senior", "middle", order, upgrade="sprt", next_up=False) == "middle"
    assert sp.product_grade("confirmed", "senior", "middle", order, upgrade="sprt", next_up=True) == "senior"
    assert sp.product_grade("confirmed", "senior", "middle", order, upgrade="none") == "middle"
    assert sp.product_grade("not_confirmed", "senior", "middle", order) == "junior"
    assert sp.product_grade("needs_followup", "junior", "middle", order) == "junior"


# ---------------------------------------------------------------- движок

def test_strong_confirmed_weak_rejected_by_sprt(stand):
    e = BankEngine()
    st = e.start(direction="backend", claimed_grade="middle", stack_tags=["python"], seed=101)
    assert st["cfg"]["sprt"]["soft_max_items"] == 20 and st["cfg"]["max_items"] == 30 and st["cfg"]["ext_items"] == 0
    play(e, st, lambda it: True)
    res = e.finish(st)
    v = res.details["verdict"]
    up, lo = sp.sprt_bounds(stand.assessment_sprt_alpha, stand.assessment_sprt_beta)
    assert v["status"] == "confirmed" and v["llr"] >= up and res.confirmed, v
    assert res.details["grade_by_answers"]["rule"] == "sprt"
    assert res.details["category"] == "backend.middle"
    st = e.start(direction="backend", claimed_grade="middle", stack_tags=["python"], seed=202)
    play(e, st, lambda it: False)
    res = e.finish(st)
    v = res.details["verdict"]
    assert v["status"] == "not_confirmed" and v["llr"] <= lo and not res.confirmed, v
    assert res.details["grade_by_answers"]["product_grade"] in ("none", "intern", "junior")


def test_edge_candidate_contested_extension_at_claimed_cut(stand):
    """Кандидат ровно у порога (знает задания ниже порога, не знает выше): SPRT не решает — тест продлевается за
    обычные 20 заданий (до 30 / 90 минут), задания — у порога заявленного грейда, практических ≥ 1/3."""
    e = BankEngine()
    st = e.start(direction="backend", claimed_grade="middle", stack_tags=["python"], seed=303)
    rng = np.random.default_rng(5)

    def edge(it):  # P(верно) по модели у θ = порог: решения быть не должно
        b = float(np.mean(it["pool"]["b"]))
        return bool(rng.random() < 1 / (1 + math.exp(-1.0 * (CUT["middle"] - b))))

    play(e, st, edge)
    res = e.finish(st)
    done = [i for i in st["items"] if i["done"] and not i["canary"]]
    code = [i for i in done if i["format"] in sp.CODE_OPEN_FORMATS]
    assert len(code) >= len(done) / 3 - 1, (len(code), len(done))
    v = res.details["verdict"]
    if v["status"] == "needs_followup":  # не решено — продление использовано
        assert len(done) > 20 or res.details["time_used_s"] >= 3600 - 1, len(done)
    # после первых заданий отбор — у порога заявленного грейда: средняя трудность близко к порогу
    late = done[5:]
    assert abs(float(np.mean([np.mean(i["pool"]["b"]) for i in late])) - CUT["middle"]) < 1.0


def test_two_stage_continues_sprt_and_oral_instead_of_coin(stand):
    from types import SimpleNamespace

    from app.core.enums import TestSessionStatus
    from app.modules.assessment import two_stage as ts_mod

    e = BankEngine()
    st = None
    for seed in range(400, 440):  # ищем кандидата, у которого после основной части решения нет
        s0 = e.start(direction="backend", claimed_grade="junior", stack_tags=["python"], seed=seed)
        rng = np.random.default_rng(seed)
        play(e, s0, lambda it: bool(rng.random() < 1 / (1 + math.exp(-1.0 * (CUT["junior"] - float(np.mean(it["pool"]["b"])))))))
        r0 = e.finish(s0)
        if r0.details["verdict"]["status"] == "needs_followup":
            st, res = s0, r0
            break
    assert st is not None, "нет кандидата у порога за 40 попыток"
    er = {"confirmed": res.confirmed, "provisional": res.provisional, "theta": res.theta, "se": res.se,
          "details": {"grade_by_answers": res.details["grade_by_answers"], "verdict": res.details["verdict"]}}
    ts = SimpleNamespace(status=TestSessionStatus.finished, claimed_grade_id="junior", direction_id="backend",
                         result={"engine": e.name, "engine_result": er, "state": st, "mode": "full"})
    b = ts_mod.session_boundary(ts)
    assert b is not None and b.kind == "sprt" and b.cut_grade == "junior"
    p2 = ts_mod.ext_params(ts_mod.params(), b.cut_grade)
    st2 = e.start(direction="backend", claimed_grade="junior", stack_tags=["python"], seed=999,
                  refine_from=dict(st, final_theta=res.theta, final_se=res.se),
                  seen={i["family_id"]: 0 for i in st["items"]},
                  refine={**b.as_dict(), "level": p2["level"], "items": int(p2["items"]), "minutes": int(p2["minutes"]),
                          "confirm": p2["confirm"], "confirm_up": p2["confirm_up"], "floor": p2["floor"],
                          "source_session_id": "t"})
    play(e, st2, lambda it: float(np.mean(it["pool"]["b"])) < CUT["junior"])  # строго у порога
    res2 = e.finish(st2)
    v2 = res2.details["verdict"]
    two = res2.details["two_stage"]
    assert two["rule"] == "sprt" and two["verdict"] == v2["status"]
    new = [i for i in st2["items"] if i["done"] and not i["canary"]]
    assert 1 <= len(new) <= int(p2["items"]) and all(i["time_limit_s"] <= 420 for i in new)
    if v2["status"] == "needs_followup":  # решения нет и после второго этапа — устная защита, а не монетка
        assert v2["followup"]["oral_defense_required"] and two["oral_defense_required"] and not two["passed"]
    else:
        assert two["passed"] == (v2["status"] == "confirmed")


# ---------------------------------------------------------------- сквозной путь API

def _state(sid: str) -> dict:
    from app.modules.assessment.models import TestSession

    with SessionLocal() as db:
        return db.get(TestSession, uuid.UUID(sid)).result["state"]


def _api_run(client, t, policy) -> dict:
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "middle"}, headers=H(t))
    assert r.status_code == 201, r.text
    s = r.json()
    sid = s["session_id"]
    n = 0
    while s["item"]:
        it_pub = s["item"]
        it = next(i for i in _state(sid)["items"] if i["token"] == it_pub["item_id"])
        r = client.post(f"/api/assessment/sessions/{sid}/answers", headers=H(t), json={
            "item_id": it_pub["item_id"], "answer": oracle(it, it_pub["step"] or 1, policy(it)), "step": it_pub["step"],
            "time_spent_ms": 60000})
        assert r.status_code == 200, r.text
        s = r.json()
        n += 1
        assert n < 120
    res = client.post(f"/api/assessment/sessions/{sid}/finish", headers=H(t)).json()
    again = client.get(f"/api/assessment/sessions/{sid}/result", headers=H(t)).json()
    return {"finish": res, "result": again, "sid": sid}


def test_api_end_to_end_verdict(client, monkeypatch, stand):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "assessment_engine", "bank")
    monkeypatch.setattr(be, "time", _Clock())
    t = register_and_verify(client, email="sprt2@example.com")
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    out = _api_run(client, t, lambda it: True)
    res = out["finish"]
    v = res["details"]["verdict"]
    assert v["status"] == "confirmed" and v["title"] == "Подтверждён", v
    assert res["confirmed"] and res["category_id"] == "backend.middle"
    assert res["grade_by_answers"]["rule"] == "sprt" and res["grade_by_answers"]["product_grade"] in ("middle", "senior")
    assert "theta_wle" not in json.dumps(res["grade_by_answers"])
    assert out["result"]["details"]["verdict"]["status"] == "confirmed"
    raw = json.dumps(res, ensure_ascii=False)
    for secret in ("answer_key", "rubric"):
        assert secret not in raw
    # объяснение — простыми словами, без внутренних обозначений
    for jargon in ("LLR", "SPRT", "θ", "IRT", "WLE"):
        assert jargon not in v["explanation"]
