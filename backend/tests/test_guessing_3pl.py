"""Оценка уровня с угадыванием (ASSESSMENT_GUESSING_3PL, А4 21.10): бот со случайными ответами и «всегда самый
длинный вариант» проходят НАСТОЯЩИЙ тест через движок (реальные варианты и проверка ответа) и не получают
подтверждённый Junior. Без угадывания в оценке (2PL при a = 3,0 у части банка) удачные угадывания у границы давали
уверенное «подтверждён» — найдено ботами cheat_bots.py."""
import pytest

from app.core.config import get_settings


@pytest.fixture
def profile(monkeypatch):
    s = get_settings()
    for k, v in {"assessment_guessing_3pl": True, "assessment_confirm_level": 0.8, "assessment_max_items": 20,
                 "assessment_two_stage_confirm": 0.5, "assessment_code_quota_ext": True,
                 "assessment_two_stage_enabled": True}.items():
        monkeypatch.setattr(s, k, v)
    return s


@pytest.mark.parametrize("strategy", ["random", "longest"])
def test_guessing_bots_do_not_get_confirmed_junior(profile, strategy, monkeypatch):
    from app.modules.validation import cheat_bots

    monkeypatch.setattr(cheat_bots, "CLAIMS", ("junior",))
    bots = cheat_bots.Bots(seed=4242)
    bots.directions = ["backend", "frontend", "qa"]
    rows = [bots.attempt(strategy, 0) for _ in range(12)]
    confirmed = sum(r["false_confirmed"] for r in rows)
    assert confirmed <= 1, f"{strategy}: подтверждён Junior в {confirmed} из 12 попыток"


def test_estimate_with_guessing_is_lower_for_lucky_mcq(profile):
    """Одни и те же ответы (2 верных из 6 вопросов с выбором у порога Junior): с угадыванием оценка ниже."""
    import numpy as np

    from app.modules.assessment.bank_engine import BankEngine

    e = BankEngine()
    st = e.start(direction="backend", claimed_grade="junior", stack_tags=[], seed=7)
    sess = e._rebuild(st)
    mcq = [i for i in sess.scored_pool if i.format == "mcq_concept" and not i.canary][:6]
    for k, it in enumerate(mcq):
        sess.record(it, [1.0 if k < 2 else 0.0], log_t=4.0, time_s=60)
    th_3pl = sess.theta
    profile.assessment_guessing_3pl = False
    th_2pl = sess._estimate().theta
    assert th_3pl < th_2pl
    assert np.isfinite(th_3pl)
