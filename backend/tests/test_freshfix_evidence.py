"""Ф6 (Н5): тест и задание работодателя — раздельные исходы в объяснениях; «0 из 1» не выглядит подтверждением."""
import uuid

from app.core.enums import EvidenceLevel, FactSource
from app.modules.profiles.facts import merge_skill, skill_check_text, skill_confirmed, skill_evidence_text
from app.modules.profiles.models import CandidateFact


def _fact(correct, total, origin=None):
    v = {"score": round(correct / total, 4), "correct": correct, "total": total}
    if origin:
        v["origin"] = origin
    return CandidateFact(user_id=uuid.uuid4(), kind="skill", key="docker", title="Docker", value=v,
                         evidence_level=EvidenceLevel.T1, source=FactSource.probe if origin else FactSource.test,
                         source_ref=("assignment:x" if origin else "test_session:x"))


def test_failed_assignment_next_to_passed_test_is_not_called_confirmation():
    # случай И20: «Docker — подтверждено заданием работодателя (0 из 1) и заданиями теста (1 из 1)»
    m = merge_skill(_fact(0, 1, "assignment"), _fact(1, 1))
    assert skill_confirmed(m)  # слитый факт и скор — как раньше (порядок match-v1 не меняется)
    txt = skill_evidence_text(m)
    assert "задание работодателя — не выполнено, 0 из 1" in txt and "тест — подтверждено, 1 из 1" in txt.lower()
    assert "Подтверждено заданием работодателя" not in txt


def test_partial_and_passed_assignment_outcomes():
    m = merge_skill(_fact(1, 1), _fact(4, 5, "assignment"))
    assert skill_evidence_text(m) == "Тест — подтверждено, 1 из 1; задание работодателя — выполнено, 4 из 5"
    m2 = merge_skill(_fact(1, 1), _fact(1, 5, "assignment"))
    assert "задание работодателя — ниже порога, 1 из 5" in skill_evidence_text(m2)


def test_check_text_below_threshold():
    single = _fact(1, 3)
    assert not skill_confirmed(single)
    assert skill_check_text(single) == "Проверено заданиями: 1 из 3 — ниже порога подтверждения"
    m = merge_skill(_fact(1, 3), _fact(0, 1, "assignment"))
    assert not skill_confirmed(m)
    assert skill_check_text(m) == "Не подтверждено: тест — ниже порога, 1 из 3; задание работодателя — не выполнено, 0 из 1"
