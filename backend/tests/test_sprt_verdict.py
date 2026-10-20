"""Тесты классификационного адаптивного отбора у порогов, последовательного теста SPRT, трёхзначного вердикта,
поддержки формата incident_sim (А3) и интерфейса Боевого этапа (А9).
"""
from __future__ import annotations

import pytest

from app.modules.assessment import sprt
from app.modules.assessment.bank_engine import BankEngine
from app.modules.assessment.engine import ItemPublic


def test_sprt_bound_and_step_llr():
    a = sprt.sprt_bound(0.02)
    assert a == pytest.approx(3.89182, abs=1e-4)
    # Верный ответ на задание у порога 0.0 даёт положительный вклад в LLR, неверный — отрицательный
    llr_pos = sprt.step_llr([1.0], [1.3], [0.0], 0.0, fmt="find_bug", delta=0.35)
    llr_neg = sprt.step_llr([0.0], [1.3], [0.0], 0.0, fmt="find_bug", delta=0.35)
    assert llr_pos > 0.3
    assert llr_neg < -0.3


def test_filter_code_open_pool_enforces_one_third():
    class DummyItem:
        def __init__(self, fid: str, fmt: str):
            self.family_id = fid
            self.format = fmt

    pool = [DummyItem("m1", "mcq_concept"), DummyItem("m2", "mcq_concept"), DummyItem("c1", "find_bug")]
    # На 3-м задании (n_scored = 2, n_code_open = 0) выбирается кодовое/открытое задание
    filtered = sprt.filter_code_open_pool(pool, n_scored=2, n_code_open=0)
    assert len(filtered) == 1 and filtered[0].family_id == "c1"
    # На 1-м задании (n_scored = 0, n_code_open = 0) все задания доступны
    filtered0 = sprt.filter_code_open_pool(pool, n_scored=0, n_code_open=0)
    assert len(filtered0) == 3


def test_three_valued_verdict_states():
    done_strong = [
        {"canary": False, "done": True, "format": "find_bug", "x": [1.0], "pool": {"a": [1.35], "b": [0.0]}}
        for _ in range(10)
    ]
    v_conf = sprt.compute_verdict(
        done_strong, {}, "middle", theta=0.85, se=0.28, confirmed=True, assigned_grade="middle"
    )
    assert v_conf.status == "confirmed"
    assert v_conf.confident is True
    assert v_conf.code_open_count == 10

    done_border = [
        {"canary": False, "done": True, "format": "mcq_concept", "x": [1.0 if i % 2 == 0 else 0.0], "pool": {"a": [1.0], "b": [0.0]}}
        for i in range(10)
    ]
    v_foll = sprt.compute_verdict(
        done_border, {}, "middle", theta=0.05, se=0.35, confirmed=False, assigned_grade="none"
    )
    assert v_foll.status == "needs_followup"
    assert v_foll.confident is False
    assert v_foll.followup_needed is True
    assert v_foll.followup_minutes == 15

    done_weak = [
        {"canary": False, "done": True, "format": "find_bug", "x": [0.0], "pool": {"a": [1.35], "b": [0.0]}}
        for _ in range(10)
    ]
    v_rej = sprt.compute_verdict(
        done_weak, {}, "middle", theta=-0.95, se=0.28, confirmed=False, assigned_grade="none"
    )
    assert v_rej.status == "not_confirmed"
    assert v_rej.confident is True


def test_incident_stage_resolves_senior_followup():
    done_border = [
        {"canary": False, "done": True, "format": "mcq_concept", "x": [1.0 if i % 2 == 0 else 0.0], "pool": {"a": [1.0], "b": [1.0]}}
        for i in range(10)
    ]
    # Без боевого этапа у границы Senior (theta = 1.05, se = 0.36) — needs_followup
    v0 = sprt.compute_verdict(done_border, {}, "senior", theta=1.05, se=0.36, confirmed=True, assigned_grade="senior")
    assert v0.status == "needs_followup"
    assert v0.as_dict()["followup"]["incident_recommended"] is True

    # С успешным боевым этапом инцидента (score = 0.88) — вердикт переходит в confirmed, SE сужается
    inc = {
        "scenario_id": "inc_db_pool_exhaustion",
        "target_grade": "senior",
        "status": "completed",
        "actions_score": 0.90,
        "rubric_score": 0.86,
        "mttr_s": 180,
    }
    v1 = sprt.compute_verdict(
        done_border, {}, "senior", theta=1.05, se=0.36, confirmed=True, assigned_grade="senior", incident_stage=inc
    )
    assert v1.status == "confirmed"
    assert v1.confident is True
    assert v1.incident_stage is not None
    assert v1.incident_stage["passed"] is True
    assert v1.incident_stage["se_after"] < v1.incident_stage["se_before"]


def test_incident_sim_format_in_bank_engine():
    assert BankEngine._answer_kind({"format": "incident_sim"}, 1) == "option"
    assert BankEngine._answer_kind({"format": "incident_sim"}, 2) == "option"
    assert BankEngine._answer_kind({"format": "incident_sim"}, 3) == "text"
    assert BankEngine.text_parts({"format": "incident_sim"}) == [2]
    pub = ItemPublic(
        item_id="tok1", position=1, total=10, format="incident_sim", stem="Разберите инцидент",
        incident={"service": "payments-api", "release": "2026.10.20"},
    )
    assert pub.incident["service"] == "payments-api"


def test_format_gap_and_integrity_followup_unified():
    from app.modules.assessment.integrity import FORMAT_GAP_TITLE, assess, format_gap_logits

    # 4 идеальных ответа на сложных MCQ (b = 1.5) при 3 провалах на базовом коде (b = -0.5) → разрыв > 0.80 логита
    items = [
        {"format": "mcq_concept", "canary": False, "time_s": 40.0, "time_limit_s": 120, "score": 1.0, "b": 1.5, "a": 1.2}
        for _ in range(4)
    ] + [
        {"format": "find_bug", "canary": False, "time_s": 90.0, "time_limit_s": 180, "score": 0.0, "b": -0.5, "a": 1.35}
        for _ in range(3)
    ]
    fg = format_gap_logits(items)
    assert fg is not None and fg["flagged"] is True
    assert fg["gap_logits"] > 0.80
    assert FORMAT_GAP_TITLE in fg["employer_reason"]

    integ = assess(items, theta=0.8)
    assert integ["signals"]["format_gap_flag"] is True
    assert any(FORMAT_GAP_TITLE in r for r in integ["reasons"])

    # Единый контур compute_verdict переводит вердикт в needs_followup с устной защитой и фактором "form_gap"
    done_for_v = [
        {"canary": False, "done": True, "format": it["format"], "x": [it["score"]], "pool": {"a": [it["a"]], "b": [it["b"]]}}
        for it in items
    ]
    v = sprt.compute_verdict(
        done_for_v, {}, "middle", theta=0.65, se=0.30, confirmed=True, assigned_grade="middle",
        suspicious={"integrity": integ},
    )
    assert v.status == "needs_followup"
    assert v.oral_defense_required is True
    assert "form_gap" in (v.integrity_followup or {}).get("triggered_factors", [])


def test_item_appeal_recomputes_verdict():
    eng = BankEngine()
    st = eng.start(direction="backend", claimed_grade="middle", stack_tags=["python"], seed=42)
    it = eng.next_item(st)
    assert it is not None
    # Завершаем задание с неверным ответом и подаём апелляцию
    st["items"][0]["x"] = [0.0]
    st["items"][0]["done"] = True
    rec = eng.submit_appeal(st, item_id=it.item_id, reason="Неоднозначное условие задачи", actor="cand@example.org")
    assert rec is not None
    assert rec["status"] == "under_review"
    assert len(eng.list_appeals(st)) == 1
    res = eng.resolve_appeal(st, item_id=it.item_id, decision="uphold_candidate", score=1.0, comment="Апелляция удовлетворена")
    assert res is not None and res["status"] == "resolved_upheld"
    assert st["items"][0]["x"] == [1.0]

