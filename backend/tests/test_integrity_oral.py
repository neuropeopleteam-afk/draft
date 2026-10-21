"""Экспериментальный флаг INTEGRITY_ORAL (по умолчанию выключен; на стенде НЕ включается — решение штаба 21.10 по
рецензии А15).

Флаг: одиночная низкая достоверность итога (integrity level «low», ≥ 3 балла; это НЕ правило А6
anticheat.behavioral_followup) → грейд не подтверждается сразу, итог решает короткий устный этап (без бана и без
понижения). Флаг 0 — поведение прежнее (решение «доп. этап» — только правило А6: 2+ независимых сигнала / ловушка).
Главная проверка — регрессия «флаг 0 = как было»; ветка флага 1 проверена, чтобы код за флагом не был мёртвым.

Проверки: функция вердикта (флаг 0 / 1, уровни low / medium, «не подтверждён» не превращается в устный этап) и
сквозной путь API (start → next → answer с сигналами интерфейса → finish → result) с включённым и выключенным флагом.
"""
from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.modules.assessment import bank_engine as be
from app.modules.assessment import sprt
from tests.conftest import register_and_verify
from tests.test_bank_engine import oracle
from tests.test_day2_rules import ONBOARDING, H
from tests.test_sprt_v2 import _Clock, _state, stand  # noqa: F401 — фикстура профиля стенда

# Достоверность «низкая» по баллам (3), но ровно один независимый сигнал (вставка) — правило А6 «2+ сигнала»
# доп. этап само по себе не назначает: так видно, что меняет именно флаг.
LOW_ONE_SIGNAL = {
    "level": "low", "points": 3, "title": "низкая",
    "signals": {"paste_items": 2, "paste_chars": 600},
    "reasons": ["Вставка готового текста в ответ: 2 задания, 600 символов"],
    "kinds": ["assist"],
}
MEDIUM = {**LOW_ONE_SIGNAL, "level": "medium", "points": 1,
          "signals": {"paste_items": 1, "paste_chars": 300}}

DONE_STRONG = [
    {"canary": False, "done": True, "format": "find_bug", "x": [1.0], "pool": {"a": [1.35], "b": [0.0]}}
    for _ in range(10)
]
DONE_WEAK = [
    {"canary": False, "done": True, "format": "find_bug", "x": [0.0], "pool": {"a": [1.35], "b": [0.0]}}
    for _ in range(10)
]


def _verdict(integ: dict, *, strong: bool = True):
    if strong:
        return sprt.compute_verdict(DONE_STRONG, {}, "middle", theta=0.85, se=0.28, confirmed=True,
                                    assigned_grade="middle", suspicious={"integrity": integ})
    return sprt.compute_verdict(DONE_WEAK, {}, "middle", theta=-1.2, se=0.28, confirmed=False,
                                assigned_grade="none", suspicious={"integrity": integ})


@pytest.fixture
def oral_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "integrity_oral", True)


def test_flag_is_off_by_default():
    assert get_settings().integrity_oral is False
    assert sprt._integrity_oral_on() is False


def test_flag_off_low_integrity_keeps_previous_behaviour():
    v = _verdict(LOW_ONE_SIGNAL)
    assert v.status == "confirmed" and v.assigned_grade == "middle"
    assert v.oral_defense_required is False
    assert not (v.integrity_followup or {}).get("integrity_oral")
    assert "Настей" not in v.explanation


def test_flag_on_low_integrity_goes_to_oral_stage_not_ban(oral_on):
    v = _verdict(LOW_ONE_SIGNAL)
    assert v.status == "needs_followup" and v.confident is False
    assert v.oral_defense_required is True and v.followup_needed is True
    assert v.title == sprt.VERDICT_TITLES["needs_oral_defense"]
    assert v.assigned_grade == "none"  # грейд не подтверждается сразу
    f = v.integrity_followup or {}
    assert f.get("integrity_oral") is True and f.get("followup_kind") == "oral_defense"
    assert f.get("needs_followup_stage") is True
    # Кандидату — простыми словами, без блокировок и понижения, без внутренних обозначений и сигналов
    assert "устный разговор с Настей" in v.explanation
    assert "блокировок и понижения нет" in v.explanation
    for jargon in ("LLR", "SPRT", "θ", "IRT", "points", "low", "балл"):
        assert jargon not in v.explanation
    # Публичный вид вердикта (то, что видит работодатель на карточке) — «нужен доп. этап / устная защита»
    pub = v.as_dict()
    assert pub["status"] == "needs_followup" and pub["title"] == "Нужен доп. этап / устная защита"
    assert pub["oral_defense_required"] is True and pub["followup"]["oral_defense_required"] is True
    assert pub["followup_kind"] == "oral_defense" and pub["followup"]["kind"] == "oral_defense"
    assert pub["integrity_oral"] is True


def test_flag_on_medium_integrity_unchanged(oral_on):
    v = _verdict(MEDIUM)
    assert v.status == "confirmed" and v.oral_defense_required is False
    assert not (v.integrity_followup or {}).get("integrity_oral")


def test_flag_on_not_confirmed_stays_not_confirmed(oral_on):
    """Устный этап — только для решения «да/спорно»: уверенное «не подтверждён» не превращается в устную защиту."""
    v = _verdict(LOW_ONE_SIGNAL, strong=False)
    assert v.status == "not_confirmed"
    assert v.oral_defense_required is False


def test_flag_on_clean_integrity_unchanged(oral_on):
    v = _verdict({"level": "high", "points": 0, "signals": {}, "reasons": []})
    assert v.status == "confirmed" and v.oral_defense_required is False


# ---------------------------------------------------------------- сквозной путь API

def _api_run_signals(client, t) -> dict:
    """Сильный кандидат проходит тест через API; интерфейс присылает сигналы только по первым трём заданиям, в двух
    из них — вставка готового текста (≥ 30 символов). Итог по правилу integrity.assess: вставка в 2 заданиях (2 балла)
    + ответы по большинству заданий без сигналов интерфейса (1 балл) = 3 → «низкая»."""
    r = client.post("/api/assessment/sessions", json={"claimed_grade": "middle"}, headers=H(t))
    assert r.status_code == 201, r.text
    s = r.json()
    sid = s["session_id"]
    n = 0
    while s["item"]:
        it_pub = s["item"]
        it = next(i for i in _state(sid)["items"] if i["token"] == it_pub["item_id"])
        body = {"item_id": it_pub["item_id"], "answer": oracle(it, it_pub["step"] or 1, True),
                "step": it_pub["step"], "time_spent_ms": 60000}
        if n < 3:
            body["signals"] = {"focus_lost": 0, "hidden_ms": 0, "paste": 1 if n < 2 else 0,
                               "paste_chars": 400 if n < 2 else 0, "copy": 0}
        r = client.post(f"/api/assessment/sessions/{sid}/answers", headers=H(t), json=body)
        assert r.status_code == 200, r.text
        s = r.json()
        n += 1
        assert n < 120
    res = client.post(f"/api/assessment/sessions/{sid}/finish", headers=H(t)).json()
    again = client.get(f"/api/assessment/sessions/{sid}/result", headers=H(t)).json()
    return {"finish": res, "result": again, "n": n}


@pytest.mark.parametrize("flag", [False, True])
def test_api_end_to_end_integrity_oral(client, monkeypatch, stand, flag):  # noqa: F811
    s = get_settings()
    monkeypatch.setattr(s, "assessment_engine", "bank")
    monkeypatch.setattr(s, "integrity_oral", flag)
    monkeypatch.setattr(be, "time", _Clock())
    t = register_and_verify(client, email=f"integ_oral_{int(flag)}@example.com")
    assert client.put("/api/me/onboarding", json=ONBOARDING, headers=H(t)).status_code == 200
    out = _api_run_signals(client, t)
    res = out["finish"]
    integ = res["details"]["integrity"]
    v = res["details"]["verdict"]
    assert integ["level"] == "low", integ  # предпосылка сценария: достоверность действительно низкая
    if not flag:
        # прежнее поведение: решение «доп. этап» — только правило А6 (здесь один сигнал — вставка)
        assert v["integrity_oral"] is False
        if not v["oral_defense_required"]:
            assert v["status"] == "confirmed" and res["confirmed"], v
    else:
        assert v["status"] == "needs_followup", v
        assert v["oral_defense_required"] is True
        assert v["title"] == sprt.VERDICT_TITLES["needs_oral_defense"]
        assert v["integrity_oral"] is True and v["followup"]["kind"] == "oral_defense"
        assert "устный разговор с Настей" in v["explanation"]
        assert not res["confirmed"]  # грейд не подтверждён сразу — решает устный этап
        assert out["result"]["details"]["verdict"]["status"] == "needs_followup"
