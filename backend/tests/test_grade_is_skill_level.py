"""Ответ организаторов VS.1: грейд — уровень навыков, подтверждаемый тестом; стаж — атрибут профиля и подсказка,
не условие. Проверяем тексты экрана выбора грейда (справочник) и подсказки грейда."""
from app.modules.assessment.grade_hint import build_hint
from app.modules.catalog.seed_data import GRADE_EXPERIENCE_TEXT, GRADE_SKILL_TEXT, GRADES, grade_by_experience


def test_every_grade_has_skill_description_and_experience_is_only_a_hint():
    for g in GRADES:
        assert GRADE_SKILL_TEXT[g], g
        assert "опыт" not in GRADE_SKILL_TEXT[g].lower() and "стаж" not in GRADE_SKILL_TEXT[g].lower(), g
        assert GRADE_EXPERIENCE_TEXT[g].startswith("обычно"), g


def test_grade_by_experience_is_a_hint_not_a_rule():
    # функция остаётся подсказкой: стаж не меняет грейд, его подтверждает только тест
    assert grade_by_experience(None) is None
    assert grade_by_experience(0.2) == "intern"
    assert grade_by_experience(1.0) == "junior"
    assert grade_by_experience(3.0) == "middle"
    assert grade_by_experience(7.0) == "senior"


def test_hint_texts_call_experience_an_orientation_only():
    h = build_hint(survey_years=3.0, resume={"experience_years": 3.0, "roles": [], "stack": []}, achievements=[])
    assert h["suggested"] == "middle"
    survey = next(s for s in h["signals"] if s["source"] == "survey")
    assert "обычно" in survey["text"] and "ориентир" in survey["text"]
    assert "подтверждает тест" in survey["text"]
    assert "уровень навыков" in h["note"]
    assert "стаж" in h["note"].lower()
    empty = build_hint(survey_years=None, resume=None, achievements=[])
    assert empty["suggested"] is None and "уровень навыков" in empty["note"]
