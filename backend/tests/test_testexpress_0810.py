"""Ф3 (08.10): согласованные шкалы мини-теста и экспресса, разные сюжеты мини-теста, порог «быстро», единые числа,
одно правило сроков повторов.

1. Одно отображение θ → категория (grades.category_level) с потолком по длине и погрешности: 3 из 3 мини-теста
   при θ = +1,01 ± 0,77 — Middle (предварительно), как экспресс 7 из 7 при θ = +1,40 ± 0,72, а не Senior.
2. Мини-тест: три задания — три разных семейства и сюжета (50 генераций на направление).
3. «Быстро» — относительно ожидаемого времени семейства на уровне θ и длины текста; честный быстрый Senior не
   помечается, вставка и мгновенные ответы — помечаются; в экспрессе — мягкая пометка без понижения.
4. θ и погрешность округляются один раз и выводятся одинаково: итог, подборка, приглашение, телефон гостя, ui.tsx.
5. Сроки правил (90 и 30 дней) — из настроек через /api/meta, без чисел в тексте главной.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import time

import numpy as np
import pytest

from app.core.config import get_settings
from app.core.fmt import round_half, ru_num, theta_round, theta_se
from app.jury_live import mini
from app.modules.assessment import bank_engine as be
from app.modules.assessment import integrity
from app.modules.assessment.bank_engine import BankEngine
from app.modules.assessment.grader import GradeOutcome
from app.modules.assessment.grades import (GRADE_CUTS, GRADE_ORDER, TOP_MAX_SE, TOP_MIN_ITEMS, category_level, ceiling,
                                           decide_grade, p_at_least)
from app.modules.assessment.rules import proved_lower
from tests.test_bank_engine import oracle

FRONT = Path(__file__).resolve().parents[2] / "frontend"
NODE_OK = (FRONT / "node_modules/.bin/esbuild").exists() and shutil.which("node") is not None
CLEAN = {"focus_lost": 0, "hidden_ms": 0, "paste": 0, "paste_chars": 0, "copy": 0}


@pytest.fixture
def bank(monkeypatch):
    monkeypatch.setattr(be, "grade_open", lambda **kw: GradeOutcome(status="scored", score=0.9, method="llm", model="t"))
    return BankEngine()


# ================================================================== 1. одна шкала θ → категория
def test_mini_three_of_three_is_middle_like_express():
    mini3 = category_level(1.01, 0.77, n_items=3)
    express7 = category_level(1.40, 0.72, n_items=7)
    assert (mini3.grade, mini3.preliminary) == ("middle", True)
    assert (express7.grade, express7.preliminary) == ("middle", False)
    # экспресс 7 из 7 не подтверждает Senior тем же правилом
    assert not decide_grade(1.40, 0.72, "senior", n_items=7).confirmed
    assert decide_grade(1.40, 0.72, "middle", n_items=7).confirmed


def test_ceiling_boundaries_items_and_se():
    assert ceiling(TOP_MIN_ITEMS - 1) == "middle" and ceiling(TOP_MIN_ITEMS) == "senior" and ceiling(None) == "senior"
    assert ceiling(12, TOP_MAX_SE) == "senior" and ceiling(12, TOP_MAX_SE + 1e-6) == "middle"
    strong = (3.0, 0.4)  # уверенно выше порога Senior
    for n, top in ((3, "middle"), (4, "middle"), (5, "senior"), (16, "senior")):
        lvl = category_level(*strong, n_items=n)
        assert lvl.grade == top and lvl.proven == "senior" and lvl.capped == (top != "senior"), (n, lvl)
        assert decide_grade(*strong, "senior", n_items=n).confirmed == (top == "senior")
    # потолок не мешает доказать уровень ниже: короткий тест на Senior предлагает Middle
    d = decide_grade(*strong, "senior", n_items=3)
    assert not d.confirmed and d.retake_lower == "middle" and not d.upgrade_available
    # подтверждённый Middle в коротком тесте не зовёт на Senior
    assert not decide_grade(*strong, "middle", n_items=3).upgrade_available
    # «предварительно» — только у мини-теста (меньше 5 заданий)
    assert category_level(0.5, 0.5, 3).preliminary and not category_level(0.5, 0.5, 5).preliminary


@pytest.mark.parametrize("grade", GRADE_ORDER)
def test_category_boundary_at_confirm_level(grade):
    """Граница категории — ровно P(θ ≥ порога) = порогу уверенности (настройка, Я22: 0,6; прежний 0,8):
    θ = порог + z(уровня)·SE."""
    from scipy.special import ndtri

    from app.modules.assessment.grades import confirm_level

    se = 0.4
    lv = confirm_level(se)
    at = GRADE_CUTS[grade] + float(ndtri(lv)) * se
    above, below = category_level(at + 1e-3, se, 12), category_level(at - 1e-3, se, 12)
    rank = GRADE_ORDER.index
    assert rank(above.grade) >= rank(grade) > (rank(below.grade) if below.grade != "none" else -1)
    assert p_at_least(at + 1e-3, se, grade) >= lv > p_at_least(at - 1e-3, se, grade)


def test_one_mapping_for_all_modes_grid():
    """decide_grade (полный/экспресс), proved_lower (принять уровень ниже) и category_level (мини-тест) согласованы."""
    from app.modules.assessment.grades import confirm_level

    rank = lambda g: -1 if g == "none" else GRADE_ORDER.index(g)  # noqa: E731
    for theta in np.arange(-2.6, 3.01, 0.07):
        for se in (0.3, 0.45, 0.6, 0.72, 0.8):
            for n in (3, 5, 9, None):
                lvl = category_level(float(theta), se, n)
                for claimed in GRADE_ORDER:
                    p = p_at_least(float(theta), se, claimed)
                    lv = confirm_level(se)  # Я22: порог из настройки; при SE > 0,6 — прежние 0,8
                    if abs(p - lv) < 2e-3:
                        continue  # у самой границы решения различаются только округлением вероятностей
                    d = decide_grade(float(theta), se, claimed, n_items=n)
                    assert d.confirmed == (rank(lvl.grade) >= rank(claimed)), (theta, se, n, claimed, lvl)
                    low = proved_lower(d.probabilities, claimed, lv)
                    if not d.confirmed and lvl.grade != "none" and rank(lvl.grade) < rank(claimed) and n is None:
                        assert low == lvl.grade, (theta, se, claimed, low, lvl)


def test_mini_result_preliminary_and_capped_title():
    st = mini.new_state("backend")
    while not mini.finished(st):
        it = mini.current(st)
        mini.answer(st, it["token"], int(it["key"]["value"]) if it["format"] == "find_bug" else it["key"]["value"])
    r = mini.result(st)
    assert r["grade"] == "middle" and r["preliminary"] and r["ceiling"] == "middle"
    assert r["category_title"] == "Backend · Middle (предварительно)"
    assert r["theta"] == round_half(r["theta"]) and r["se"] == round_half(r["se"])


# ================================================================== 2. разные сюжеты мини-теста
SAME_PLOT_PAIRS = [("backend.cache.invalidation_bug", "backend.cache.key_params_bug"),
                   ("frontend.sec.escape_html_bug", "frontend.sec.replace_global_bug"),
                   ("frontend.ts.type_guard_bug", "frontend.ts.typeof_null_guard_bug"),
                   ("data_ml.metrics.auc_pairwise_ties_bug", "data_ml.metrics.roc_auc_ties_bug"),
                   ("data_ml.sql.rolling_partition_bug", "data_ml.sql.rolling_window_bug")]


@pytest.mark.parametrize("a,b", SAME_PLOT_PAIRS)
def test_same_plot_pairs(a, b):
    assert mini.same_plot(a, b) and mini.same_plot(b, a)


def test_different_plots():
    assert not mini.same_plot("backend.cache.invalidation_bug", "backend.async.missing_await_bug")
    assert not mini.same_plot("common.http.status_codes", "backend.async.missing_await_bug")  # разные темы


@pytest.mark.parametrize("direction", mini.DIRECTIONS)
def test_mini_fifty_generations_distinct_families_and_plots(direction):
    rng = random.Random(f"plots-{direction}")
    for _ in range(50):
        st = mini.new_state(direction)
        while not mini.finished(st):
            it = mini.current(st)
            ok = rng.random() < 0.6
            key = it["key"]["value"]
            if it["format"] == "find_bug":
                val = int(key) if ok else (1 if int(key) != 1 else 2)
            else:
                ids = [o["id"] for o in it["public"]["options"]]
                val = key if ok else next(i for i in ids if i != key)
            mini.answer(st, it["token"], val)
        fams = [i["family_id"] for i in st["items"]]
        assert len(fams) == 3 and len(set(fams)) == 3, fams
        for i in range(3):
            for j in range(i + 1, 3):
                assert not mini.same_plot(fams[i], fams[j]), fams


# ================================================================== 3. порог «быстро»
def _read(it):
    return integrity.read_s(*integrity.text_size(it["public"]))


def _run(bank, claimed, *, times, signals=None, mode="express", seed=7, good=True):
    """Сессия банка со временем ответа по часам сервера: times(it) → секунды на задание."""
    st = bank.start(direction="backend", claimed_grade=claimed, stack_tags=[], seed=seed, mode=mode)
    while True:
        item = bank.next_item(st)
        if item is None:
            break
        it = next(i for i in st["items"] if i["token"] == item.item_id)
        it["issued_at"] = time.time() - times(it)
        sig = dict(signals(it) if signals else CLEAN)
        bank.answer(st, item.item_id, oracle(it, item.step or 1, good), 1000, step=item.step, signals=sig)
    return st, bank.finish(st)


def _fast_reasons(integ):
    return [r for r in integ["reasons"] if "быстр" in r.lower() or "мгновенн" in r.lower()]


def test_threshold_relative_to_family_level_and_text():
    # Senior на лёгком задании быстрее Junior: порог ниже
    kw = dict(text_chars=600, code_chars=500)
    assert integrity.fast_threshold_s(240, theta=1.5, b=-0.5, **kw) < integrity.fast_threshold_s(240, theta=-1, b=-0.5, **kw)
    # короткий текст — порог ниже, чем у длинного при том же рекомендуемом времени
    short = integrity.fast_threshold_s(240, text_chars=150, code_chars=0, theta=1, b=0)
    long_ = integrity.fast_threshold_s(240, text_chars=900, code_chars=700, theta=1, b=0)
    assert short < long_ and short == integrity.INSTANT_MIN_S
    # прежний порог 8 % от 240 с = 19,2 с: честные 10–15 с Senior теперь не «быстро» ни на одном задании экспресса
    for p in be._pool(1):
        if p.canary or p.time_limit_s > 240 or p.format in ("open_book_3step", "open_answer"):
            continue
        v = __import__("assessment_bank").generate(p.family_id, 4242)
        t, c = integrity.text_size(v.public_view())
        assert integrity.fast_threshold_s(p.time_limit_s, text_chars=t, code_chars=c, theta=1.4,
                                          b=float(np.mean(p.b))) <= 10.5, p.family_id
    # без длины текста (старые записи) — по ожидаемому времени; 4 с при 300 с — быстро, 120 с — нет
    assert integrity.is_fast(4, 300) and not integrity.is_fast(120, 300)


def test_honest_fast_senior_not_flagged(bank):
    """Честный быстрый Senior: 10–30 с на задание (по длине текста) при рекомендации 2–6 мин — без пометок."""
    honest = lambda it: min(30.0, max(10.0, 0.5 * _read(it)))  # noqa: E731
    for claimed, seed in (("middle", 7), ("senior", 11), ("senior", 23)):
        st, res = _run(bank, claimed, times=honest, seed=seed)
        integ = res.details["integrity"]
        assert integ["level"] == "high" and not _fast_reasons(integ), integ
        # и строгий режим (полный тест) на тех же ответах не пометил бы
        items = [{"format": i["format"], "canary": False, "time_s": i["time_s"], "time_limit_s": i["time_limit_s"],
                  "score": 1.0, "signals": CLEAN, **dict(zip(("text_chars", "code_chars"), integrity.text_size(i["public"]))),
                  "b": float(np.mean(i["pool"]["b"]))} for i in st["items"] if i["done"]]
        strict = integrity.assess(items, theta=res.theta)
        assert strict["level"] == "high" and not _fast_reasons(strict), strict


def test_supervisor_pass_express_soft_note_without_downgrade(bank):
    """Сценарий проверки 08.10: 7 из 7, 10–30 с на задание — достоверность высокая; если что-то и «быстро», то
    мягкая пометка «стоит уточнить зондом», без «аномально»."""
    rng = random.Random(5)
    st, res = _run(bank, "middle", times=lambda it: rng.uniform(10, 30))
    integ = res.details["integrity"]
    assert integ["level"] == "high" and integ["points"] == 0
    assert not any("Аномально" in r for r in integ["reasons"])
    # совсем быстрый, но не мгновенный проход в экспрессе — только мягкая пометка
    st, res = _run(bank, "middle", times=lambda it: max(integrity.instant_threshold_s(*integrity.text_size(it["public"])) + 0.5,
                                                         min(9.0, 0.3 * _read(it))))
    integ = res.details["integrity"]
    soft = [r for r in integ["reasons"] if integrity.SOFT_FAST_NOTE in r]
    assert integ["level"] == "high" and soft and soft[0].startswith("Быстрые верные ответы:"), integ
    assert integ["signals"]["fast_soft"] is True


def test_instant_answers_flagged_even_in_express(bank):
    st, res = _run(bank, "middle", times=lambda it: 1.5)
    integ = res.details["integrity"]
    assert integ["level"] != "high" and any(r.startswith("Мгновенные верные ответы") for r in integ["reasons"]), integ


def test_paste_with_fast_answers_flagged_in_express(bank):
    paste = lambda it: {**CLEAN, "paste": 1, "paste_chars": 300}  # noqa: E731
    st, res = _run(bank, "middle", times=lambda it: 30.0, signals=paste)
    integ = res.details["integrity"]
    assert integ["level"] != "high" and any("Вставка" in r for r in integ["reasons"]), integ
    # при других сигналах быстрые ответы считаются как обычно (без мягкого режима): вставка + быстро → низкая
    st, res = _run(bank, "middle", times=lambda it: integrity.instant_threshold_s(*integrity.text_size(it["public"])) + 0.5,
                   signals=paste)
    integ = res.details["integrity"]
    assert integ["level"] == "low" and integ["signals"]["fast_soft"] is False, integ
    assert any(r.startswith("Аномально быстрые верные ответы") for r in integ["reasons"]), integ


def test_copy_and_fast_in_full_mode_flagged(bank):
    st, res = _run(bank, "middle", times=lambda it: 5.0, mode="full")
    integ = res.details["integrity"]
    assert integ["level"] != "high" and any("быстрые верные" in r.lower() for r in integ["reasons"]), integ


def test_soft_note_not_shown_to_candidate():
    items = [{"format": "mcq_concept", "canary": False, "time_s": 8.0, "time_limit_s": 240, "score": 1.0,
              "signals": dict(CLEAN), "text_chars": 600, "code_chars": 400, "b": 0.0} for _ in range(7)]
    integ = integrity.assess(items, theta=1.4, soft_fast=True)
    assert integ["level"] == "high" and integrity.SOFT_FAST_NOTE in integ["reasons"][0]
    cv = json.dumps(integrity.candidate_view(integ), ensure_ascii=False)
    assert "быстр" not in cv.lower() and "зонд" not in cv.lower()
    emp = integrity.summary_for_employer(integ)
    assert emp["level"] == "high" and any(integrity.SOFT_FAST_NOTE in r for r in emp["reasons"])
    # без мягкого режима те же ответы — «аномально быстрые», достоверность ниже
    strict = integrity.assess(items, theta=1.4)
    assert strict["level"] == "medium" and strict["reasons"][0].startswith("Аномально быстрые верные ответы: 7 из 7")


# ================================================================== 4. единые числа
@pytest.mark.parametrize("v,signed_s,plain_s", [
    (0.715, "+0,72", "0,72"), (1.005, "+1,01", "1,01"), (2.675, "+2,68", "2,68"), (-0.715, "−0,72", "−0,72"),
    (1.395, "+1,40", "1,40"), (0.0, "0,00", "0,00"), (-0.001, "−0,00", "−0,00"), (0.125, "+0,13", "0,13"),
    (-1.005, "−1,01", "−1,01"), (None, "—", "—")])
def test_formatter_boundaries(v, signed_s, plain_s):
    assert ru_num(v, sign=True) == signed_s and ru_num(v) == plain_s


def test_theta_round_single_place():
    assert theta_round(1.3951, 0.7149) == (1.4, 0.71) and theta_round(0.715, 0.715) == (0.72, 0.72)
    assert theta_se(*theta_round(1.395, 0.715)) == "+1,40 ± 0,72"
    assert round_half(float("nan")) is None and round_half(None) is None


NUMS = """
import { num, signed } from "./src/components/ui";
import { daysText } from "./src/lib/meta";
const vals: number[] = JSON.parse(process.argv[2]);
const days = [1, 3, 11, 21, 22, 14, 30, 90, 111];
process.stdout.write(JSON.stringify({ nums: vals.map((v) => [signed(v), num(v)]), days: days.map(daysText) }));
"""


@pytest.mark.skipif(not NODE_OK, reason="нет node или node_modules фронтенда")
def test_python_formatter_matches_ui_tsx(tmp_path):
    """ru_num(sign=True)/ru_num == signed/num из ui.tsx (Intl ru-RU) на границах округления и случайных значениях."""
    rng = random.Random(1)
    vals = [0.715, 1.005, 2.675, -0.715, 1.395, 0.125, -1.005, 0.0, 0.3349999, 0.335, -2.4449, 0.7249]
    vals += [round(rng.uniform(-3, 3), 3) for _ in range(300)] + [rng.uniform(-3, 3) for _ in range(100)]
    entry = FRONT / f".f3_nums_{os.getpid()}.ts"
    out = tmp_path / "nums.cjs"
    try:
        entry.write_text(NUMS, encoding="utf-8")
        subprocess.run([str(FRONT / "node_modules/.bin/esbuild"), str(entry), "--bundle", "--platform=node",
                        "--format=cjs", "--jsx=automatic", "--log-level=error", "--define:import.meta.env={}",
                        "--define:import.meta.glob=__viteGlob", "--banner:js=var __viteGlob = () => ({});",
                        f"--outfile={out}"],
                       cwd=FRONT, check=True, timeout=120, env={**os.environ, "NODE_PATH": str(FRONT / "node_modules")})
    finally:
        entry.unlink(missing_ok=True)
    got = json.loads(subprocess.run(["node", str(out), json.dumps(vals)], capture_output=True, text=True, timeout=60,
                                    check=True).stdout)
    py = [[ru_num(v, sign=True), ru_num(v)] for v in vals]
    bad = [(v, a, b) for v, a, b in zip(vals, got["nums"], py) if a != b]
    assert not bad, bad[:10]
    # сроки правил в текстах интерфейса (meta.tsx daysText)
    assert got["days"] == ["1 день", "3 дня", "11 дней", "21 день", "22 дня", "14 дней", "30 дней", "90 дней", "111 дней"]


def test_express_result_rounded_once_and_explanation_matches(bank):
    for claimed, seed in (("middle", 3), ("junior", 5), ("senior", 9)):
        _, res = _run(bank, claimed, times=lambda it: 60.0, seed=seed)
        assert res.theta == round_half(res.theta) and res.se == round_half(res.se)
        # Пояснение кандидату — простыми словами, без внутренних оценок (f76ae447c, вердикт по SPRT: «без внутренних
        # оценок»; правило владельца — без θ/IRT в основном интерфейсе). Прежнее ожидание «θ = … в тексте» устарело.
        # Проверяем строже, чем раньше: в тексте нет ни θ, ни сырых чисел оценки; текст называет заявленный грейд
        # и согласован с решением (подтверждён / не подтверждён / нужен доп. этап).
        ex = res.explanation
        assert ex and "θ" not in ex and theta_se(res.theta, res.se) not in ex, ex
        assert repr(res.theta) not in ex and repr(res.se) not in ex, ex
        g = be.GRADE_RU[claimed]
        assert g in ex, ex
        if res.confirmed:
            assert "подтвержд" in ex and "не подтвержд" not in ex.split(".")[0], ex
        else:
            assert ("не подтвержд" in ex) or ("границ" in ex) or ("дополнительн" in ex), ex
        assert "Экспресс-тест" in ex, ex  # режим назван


def test_live_snapshot_same_numbers_everywhere(client, monkeypatch):
    """Мини-тест QR: телефон гостя, «Почему в подборке», приглашение, подборка работодателя — одно «θ = +x,xx ± y,yy»."""
    from tests.test_day2_rules import H
    from tests.test_jury_live import _answer, _login, _room

    monkeypatch.setattr(get_settings(), "jury_live_select_delay_s", 0)
    monkeypatch.setattr(get_settings(), "jury_live_invite_delay_s", 0)
    emp = _login(client, "employer")
    code = _room(client, emp["access_token"])["code"]
    r = client.post(f"/api/jury/live/j/{code}/start", json={"direction": "backend"})
    gt, me = r.json()["token"], r.json()["guest"]
    for _ in range(3):
        me = _answer(client, code, gt, me["item"], correct=True)
    res = me["result"]
    want = f"θ = {theta_se(res['theta'], res['se'])}"
    assert res["grade"] == "middle" and res["preliminary"] and res["category_title"].endswith("(предварительно)")
    texts = [x["text"] for x in me["selection"]["reasons"] if "θ = " in x["text"]]
    texts += [e["text"] for e in me["invite"]["evidence"] if "θ = " in e["text"]]
    assert len(texts) >= 2 and all(want in t for t in texts), (want, texts)
    assert "(предварительно)" in me["invite"]["offer_description"]
    assert any("(предварительно) по мини-тесту" in e["text"] for e in me["invite"]["evidence"])
    needs = client.get("/api/employer/needs", headers=H(emp["access_token"])).json()
    live = next(n for n in needs if n["title"] == me["selection"]["need_title"])
    v = client.get(f"/api/employer/needs/{live['id']}/selections/{me['selection']['version']}",
                   headers=H(emp["access_token"])).json()
    card = next(c for c in v["results"] if c["ref"] == me["ref"])
    why = [x["text"] for x in card.get("reasons", []) if "θ = " in x["text"]]
    assert why and all(want in t for t in why), why
    # все θ в текстах — с запятой и двумя знаками
    assert all(re.search(r"θ = [+−]?\d+,\d\d ± \d+,\d\d", t) for t in texts + why)


# ================================================================== 5. одно правило сроков
def test_meta_rules_from_settings(client, monkeypatch):
    s = get_settings()
    m = client.get("/api/meta").json()["rules"]
    assert m == {"grade_change_interval_days": s.grade_change_interval_days,
                 "retake_same_grade_days": s.retake_same_grade_days,
                 "invitation_cooldown_days": s.invitation_cooldown_days,
                 "confirm_pct": round(100 * s.assessment_confirm_level),
                 # А4 8679f847 (А19 №2): длина теста на экранах — из тех же настроек движка; ожидание дополнено, не ослаблено
                 "test_len": {"min_items": s.assessment_min_items, "max_items": s.assessment_max_items,
                              "max_minutes": s.assessment_max_minutes,
                              "contested_max_items": s.assessment_contested_max_items,
                              "contested_max_minutes": s.assessment_contested_max_minutes,
                              "two_stage_items": s.assessment_two_stage_items,
                              "two_stage_minutes": s.assessment_two_stage_minutes}}
    monkeypatch.setattr(s, "retake_same_grade_days", 21)
    monkeypatch.setattr(s, "assessment_max_items", 20)
    assert client.get("/api/meta").json()["rules"]["test_len"]["max_items"] == 20  # читается на запросе, не при старте
    assert client.get("/api/meta").json()["rules"]["retake_same_grade_days"] == 21


def test_frontend_rule_texts_not_hardcoded():
    landing = (FRONT / "src/pages/Landing.tsx").read_text(encoding="utf-8")
    assert "раз в 90 дней" not in landing and "за 30 дней" not in landing
    assert "useRules" in landing and "grade_change_interval_days" in landing and "retake_same_grade_days" in landing
    contact = (FRONT / "src/pages/employer/Contact.tsx").read_text(encoding="utf-8")
    assert "раза в 30 дней" not in contact and "invitation_cooldown_days" in contact
    cat = (FRONT / "src/pages/candidate/Category.tsx").read_text(encoding="utf-8")
    assert "Правила 90 и 30 дней" not in cat
