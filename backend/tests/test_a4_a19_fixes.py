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
    # начинается с решения вердикта; на экране итога фронтенд выводит только остаток (без повтора, А19 №5)
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


# ---- экспресс: семейства «вне ряда» (список А3) и служебная шапка генератора при показе ----------------------------

def test_display_stem_strips_generator_header_only():
    from app.modules.assessment.display import display_stem

    a = ("Обратный расчёт входа «документов в сутки, тыс.» с учётом факторов: шапка документа, события статусов. "
         "По контракту «шина заказов маркетплейса» за сутки передаётся X тыс. документов.")
    b = ("Прямой расчёт показателя «МБ позиций в сутки» с учётом факторов: шапка документа, события статусов. "
         "По контракту «шина заказов маркетплейса» за сутки передаётся 660 тыс. документов.")
    c = ("Обратный расчёт входа «скорость канала, Мбит/с» с учётом факторов: code splitting, разбор и компиляция, "
         "сетевые RTT, запас на p75, гидратация. Бандл страницы «поиск отелей» — 180 КБ после сжатия, канал — X Мбит/с.")
    assert display_stem(a).startswith("По контракту «шина заказов маркетплейса» за сутки передаётся X")
    assert display_stem(b).startswith("По контракту") and "660 тыс." in display_stem(b)
    assert display_stem(c).startswith("Бандл страницы «поиск отелей»")
    plain = "Сервис принимает 1 200 запросов в секунду. Сколько нужно реплик?"
    assert display_stem(plain) == plain and display_stem(None) is None and display_stem("") == ""


def test_express_excludes_out_of_range_only_in_express(monkeypatch):
    import app.modules.assessment.bank_engine as be
    from app.modules.assessment.grader import GradeOutcome
    from tests.test_testexpress_0810 import _run

    ex = be.express_excluded()
    assert len(ex) == 601  # список А3 (express_scan_2110.json), банк не меняется
    monkeypatch.setattr(be, "grade_open", lambda **kw: GradeOutcome(status="scored", score=0.9, method="llm", model="t"))
    bank = be.BankEngine()
    fams = {f.family_id if hasattr(f, "family_id") else f for f in getattr(bank, "families", {}) or {}}
    if fams:
        assert ex <= fams
    got_express, got_full = set(), set()
    for seed in (1, 2, 3, 4):
        st, _ = _run(bank, "middle", times=lambda it: 60.0, seed=seed, mode="express")
        got_express |= {i["family_id"] for i in st["items"]}
    assert got_express and not (got_express & ex)
    # основной тест: пул тот же — исключение не применяется (семейства из списка по-прежнему могут выдаваться)
    calls = []
    real = be.express_excluded
    monkeypatch.setattr(be, "express_excluded", lambda: calls.append(1) or real())
    st, _ = _run(bank, "middle", times=lambda it: 60.0, seed=5, mode="full")
    assert st["items"] and not calls
