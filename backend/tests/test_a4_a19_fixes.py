"""А4: правки по обходу А19 (21.10) — один порог в пояснении итога, «уровень ниже» при угадывании, поставщики в NUMBERS."""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

from app.modules.assessment.bank_engine import BankEngine
from app.modules.assessment.service import _guessing_flag

ROOT = Path(__file__).resolve().parents[2]


def _dec(p_claim: float, confirmed: bool):
    return SimpleNamespace(probabilities={"junior": 1 - p_claim, "middle": p_claim}, confirmed=confirmed,
                           retake_lower=None, upgrade_available=False, provisional=False)


def test_express_explanation_single_threshold_from_verdict():
    """№5: при трёхзначном вердикте пояснение экспресса не повторяет вероятность со вторым порогом (≥ 65 %)."""
    vd = {"status": "not_confirmed", "explanation": "Уровень Middle не подтверждён: вероятность 0 % (уверенное решение «нет» — до 20 %)."}
    s = BankEngine._explain_express(_dec(0.004, False), "middle", {"n_scored": 8}, vd)
    assert s.startswith(vd["explanation"])
    assert "нужно ≥" not in s and "менее 1 %" not in s
    assert len(re.findall(r"\d+ %", s)) == 2  # только 0 % и 20 % из вердикта


def test_express_explanation_without_verdict_keeps_rule():
    s = BankEngine._explain_express(_dec(0.004, False), "middle", {"n_scored": 8}, None)
    assert "нужно ≥" in s  # прежний текст, если вердикта нет


def test_guessing_flag_blocks_accept_lower():
    er = {"details": {"integrity": {"reasons": ["Много мгновенных неверных ответов (5 из 8) — похоже на угадывание"]}}}
    assert _guessing_flag(er) is True
    assert _guessing_flag({"details": {"integrity": {"reasons": ["Сигналов нарушений нет"]}}}) is False
    assert _guessing_flag({}) is False


def test_numbers_have_no_vendor_names():
    """Поставщики моделей на сайте не называются: NUMBERS и его копия во фронтенде — без названий моделей."""
    pat = re.compile(r"(?i)claude|sonnet|deepseek|grok|kimi|gemini|qwen|yandexgpt|openrouter|anthropic|gpt-oss")
    for rel in ("docs/NUMBERS.json", "frontend/src/data/numbers.json"):
        txt = (ROOT / rel).read_text(encoding="utf-8")
        assert not pat.search(txt), (rel, pat.search(txt).group(0))
        json.loads(txt)
