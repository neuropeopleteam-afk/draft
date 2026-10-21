"""P0-1 рецензии А15 (21.10): итог второго этапа по правилу SPRT — категория только при «подтверждён».

Раньше as_result делал заявленным уровень по двум сессиям при любом итоге, кроме «none»: кандидат без решения или
с «не подтверждён» получал категорию (FC продукта 7,0 % против 0,7 % в симуляции).
"""
from types import SimpleNamespace

from app.modules.assessment.engine import EngineResult
from app.modules.assessment.two_stage import as_result, explain_sprt


def _res(verdict: str, final_grade: str, claimed: str = "middle", confirmed: bool = False) -> EngineResult:
    return EngineResult(engine="bank_irt", theta=0.1, se=0.3, claimed_grade=claimed, point_grade=final_grade,
                        confirmed=confirmed, upgrade_available=False, retake_lower=None, probabilities={},
                        answered=20, correct=12, skills={}, explanation="",
                        details={"two_stage": {"rule": "sprt", "verdict": verdict, "final_grade": final_grade,
                                               "label": "граница Middle", "new_items": 8, "passed": verdict == "confirmed"}})


def test_needs_followup_no_category():
    ts = SimpleNamespace(claimed_grade_id="middle")
    r = as_result(ts, _res("needs_followup", "middle"))
    assert r.confirmed is False and r.retake_lower is None and r.provisional is False
    assert ts.claimed_grade_id == "middle"  # заявленный не переписан уровнем по ответам
    assert "предварительно" in r.explanation and "устной защиты" in r.explanation


def test_needs_followup_above_claim_still_no_category():
    ts = SimpleNamespace(claimed_grade_id="middle")
    r = as_result(ts, _res("needs_followup", "senior"))
    assert r.confirmed is False and ts.claimed_grade_id == "middle"


def test_not_confirmed_offers_lower_not_assigns():
    ts = SimpleNamespace(claimed_grade_id="middle")
    r = as_result(ts, _res("not_confirmed", "junior"))
    assert r.confirmed is False and r.retake_lower == "junior" and ts.claimed_grade_id == "middle"
    assert "принудительного понижения нет" in r.explanation


def test_confirmed_keeps_claim_and_offers_upgrade():
    ts = SimpleNamespace(claimed_grade_id="middle")
    r = as_result(ts, _res("confirmed", "senior", confirmed=True))
    assert r.confirmed is True and r.claimed_grade == "middle" and ts.claimed_grade_id == "middle"
    assert r.upgrade_available is True
    assert "подтверждён" in explain_sprt({"verdict": "confirmed", "final_grade": "middle", "new_items": 8}, "middle")
