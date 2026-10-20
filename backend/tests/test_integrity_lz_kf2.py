"""KF2: анти-ИИ щит → устная защита. Индекс person-fit l_z (Drasgow–Levine–Williams, 1985) в достоверности попытки,
мост «подозрение античита → 3-минутная устная защита по коду и решениям», паспорт честности (IntegrityBadge, 5 контуров),
расширенный перехват снимка экрана (Win+Shift+S, Cmd+Shift+3/4/5) без прерывания теста."""
from __future__ import annotations

import math
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.enums import TestSessionStatus
from app.modules.assessment import integrity as ig
from app.modules.assessment.bank_engine import BankEngine
from app.modules.assessment.models import TestSession as TSession  # без «Test» в имени — pytest не собирает
from app.modules.interview import context as cx
from app.modules.interview import service as svc
from app.modules.interview.models import InterviewSession
from tests.test_bank_engine import bank, run_session  # noqa: F401 — фикстура банка
from tests.test_day2_rules import H, candidate_with_category, employer, my_ref

FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"
DOCS = Path(__file__).resolve().parents[2] / "docs"

# Задания от лёгких к трудным (b), a = 1,5
LADDER = [(1.5, b) for b in (-2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0)]


def _ref_lz(resp, theta):
    """Эталон по формулам статьи (независимая запись)."""
    l0 = e = v = 0.0
    for a, b, x in resp:
        p = 1 / (1 + math.exp(-a * (theta - b)))
        l0 += x * math.log(p) + (1 - x) * math.log(1 - p)
        e += p * math.log(p) + (1 - p) * math.log(1 - p)
        v += p * (1 - p) * math.log(p / (1 - p)) ** 2
    return (l0 - e) / math.sqrt(v)


# ------------------------------------------------------------------ 1. person_fit_lz — чистая функция

def test_lz_none_below_six_items_and_bad_input():
    assert ig.person_fit_lz([], 0.0) is None
    assert ig.person_fit_lz([(1.0, 0.0, 1)] * 5, 0.0) is None
    assert ig.person_fit_lz([(1.0, 0.0, 1)] * 6, float("nan")) is None
    assert ig.person_fit_lz([(1.0, 0.0, 1)] * 6, "x") is None  # type: ignore[arg-type]
    # мусорные строки отбрасываются — остаётся меньше шести
    assert ig.person_fit_lz([(1.0, 0.0, 1)] * 5 + [("a", None, 1)], 0.0) is None
    # нулевые дискриминации — нет дисперсии
    assert ig.person_fit_lz([(0.0, 0.0, 1)] * 8, 0.0) is None
    assert ig.LZ_MIN_ITEMS == 6


def test_lz_matches_reference_formula():
    theta = 0.3
    resp = [(a, b, 1.0 if b < 0.6 else 0.0) for a, b in LADDER]
    assert ig.person_fit_lz(resp, theta) == pytest.approx(_ref_lz(resp, theta), abs=1e-3)
    mixed = [(0.8, -1.0, 1), (1.2, 0.4, 0), (2.0, 0.1, 1), (1.0, 1.3, 0), (0.6, -0.4, 0), (1.7, 0.9, 1), (1.1, 0.0, 1)]
    assert ig.person_fit_lz(mixed, -0.2) == pytest.approx(_ref_lz(mixed, -0.2), abs=1e-3)


def test_lz_consistent_vs_aberrant_pattern():
    theta = 0.0
    # согласованный (Гуттман): решены лёгкие, провалены трудные — l_z положительный
    guttman = [(a, b, 1.0 if b <= 0 else 0.0) for a, b in LADDER]
    # аберрантный: провалены лёгкие, решены трудные — подсказка на трудных заданиях
    aberrant = [(a, b, 0.0 if b <= 0 else 1.0) for a, b in LADDER]
    lz_ok, lz_bad = ig.person_fit_lz(guttman, theta), ig.person_fit_lz(aberrant, theta)
    assert lz_ok > 0.5
    assert lz_bad < ig.LZ_ALARM < ig.LZ_WARN
    # дробный балл (развёрнутый ответ) дихотомизируется по 0,5
    frac = [(a, b, 0.9 if b <= 0 else 0.2) for a, b in LADDER]
    assert ig.person_fit_lz(frac, theta) == pytest.approx(lz_ok)


def test_lz_points_thresholds():
    assert ig.lz_points(None) == 0
    assert ig.lz_points(-1.99) == 0
    assert ig.lz_points(-2.0) == 0  # строго меньше −2
    assert ig.lz_points(-2.01) == 1
    assert ig.lz_points(-3.0) == 1
    assert ig.lz_points(-3.01) == 2


# ------------------------------------------------------------------ 1. assess(lz=…)

def _done(n=8):
    return [{"format": "mcq_concept", "canary": False, "time_s": 40.0, "time_limit_s": 120, "score": 1.0,
             "text_chars": 200, "code_chars": 0, "b": 0.0, "signals": {"focus_lost": 0, "hidden_ms": 0, "paste": 0, "paste_chars": 0,
                                                  "copy": 0, "fs_exit": 0, "fs_ms": 30000, "fs_out_ms": 0}}
            for i in range(n)]


def test_assess_lz_reason_points_and_signal():
    base = ig.assess(_done(), theta=0.0)
    assert base["signals"]["lz"] is None and not base["signals"]["lz_flag"] and ig.LZ_REASON not in base["reasons"]
    one = ig.assess(_done(), theta=0.0, lz=-2.4)
    assert one["points"] == base["points"] + 1 and one["signals"]["lz"] == -2.4 and one["signals"]["lz_flag"]
    assert ig.LZ_REASON in one["reasons"]
    assert ig.LZ_REASON == ("Паттерн ответов не согласуется с уровнем (индекс l_z < −2,0): ошибки на базовых заданиях "
                            "при верных ответах на сложных")
    two = ig.assess(_done(), theta=0.0, lz=-3.4)
    assert two["points"] == base["points"] + 2 and two["level"] in ("medium", "low")
    # не пометка: −1,5 — в пределах нормы
    ok = ig.assess(_done(), theta=0.0, lz=-1.5)
    assert ok["points"] == base["points"] and ig.LZ_REASON not in ok["reasons"]
    # Р27: вид причины — «признаки использования подсказок», без механики для кандидата
    assert ig.reason_kind(ig.LZ_REASON) == "assist"
    view = ig.candidate_view(two)
    assert "l_z" not in str(view) and "Паттерн" not in str(view)


# ------------------------------------------------------------------ 1. bank_engine.finish

def test_bank_lz_responses_skip_canary_and_pending():
    pi = SimpleNamespace(a_eff=[1.2, 0.8], b=[-0.5, 0.7])
    done = [{"family_id": "A", "x": [1, 0.3]}, {"family_id": "A", "canary": True, "x": [1, 1]},
            {"family_id": "A", "x": [None, 0.6]}, {"family_id": "missing", "x": [1]}]
    rows = BankEngine._lz_responses(done, {"A": pi})
    assert rows == [(1.2, -0.5, 1.0), (0.8, 0.7, 0.0), (0.8, 0.7, 1.0)]


def test_bank_finish_stores_lz_in_integrity_signals(bank):  # noqa: F811
    st, res, _ = run_session(bank, "middle", "backend", "good")
    integ = res.details["integrity"]
    assert "lz" in integ["signals"]
    lz = integ["signals"]["lz"]
    assert lz is None or isinstance(lz, float)
    if lz is not None:  # у «знающего» кандидата паттерн согласован — пометки нет
        assert lz > ig.LZ_WARN and ig.LZ_REASON not in integ["reasons"]


# ------------------------------------------------------------------ 3. рекомендация устной защиты

def _integ(level="high", **sig):
    return {"level": level, "title": {"high": "высокая", "medium": "средняя", "low": "низкая"}[level],
            "points": 0, "reasons": [], "signals": {"lz": None, "ai_mark_items": 0, "preknowledge_flagged": False,
                                                    "canary_fast": 0, **sig}}


def test_defense_recommendation_rules():
    assert svc.defense_recommendation(None) == (False, None, [])
    assert svc.defense_recommendation(_integ())[0] is False
    assert svc.defense_recommendation(_integ(lz=-1.9))[0] is False
    for integ, hit in ((_integ("medium"), "level"), (_integ("low"), "level"), (_integ(lz=-2.3), "fit"),
                       (_integ(ai_mark_items=1), "origin"), (_integ(preknowledge_flagged=True), "prior"),
                       (_integ(canary_fast=2), "prior")):
        rec, why, hits = svc.defense_recommendation(integ)
        assert rec and why.startswith("Рекомендована 3-минутная устная защита") and hit in hits
    assert "l_z = −2,30" in svc.defense_recommendation(_integ(lz=-2.3))[1]


def test_passport_detailed_and_candidate_views():
    integ = _integ("medium", lz=-2.6, focus_lost_items=3, printscreen=1)
    full = svc.integrity_passport(integ, None, detailed=True)
    assert [c["id"] for c in full["contours"]] == ["prior", "fit", "origin", "screen", "live"]
    by = {c["id"]: c for c in full["contours"]}
    assert by["fit"]["status"] == "warn" and "−2,60" in by["fit"]["value"]
    assert by["screen"]["status"] == "warn" and "снимки экрана: 1" in by["screen"]["value"]
    assert by["prior"]["status"] == "ok" and by["origin"]["status"] == "ok"
    assert by["live"]["status"] == "recommended" and full["verdict"] == "recommended" and full["recommended"]
    # кандидату вне демо-режима (Р27) — без значений и названий механизмов
    cand = svc.integrity_passport(integ, None, detailed=False)
    assert not cand["detailed"] and cand["why"] == svc.CANDIDATE_WHY
    assert all(c["status"] == "checked" and c["value"] is None for c in cand["contours"][:4])
    dumped = str(cand)
    for word in ("l_z", "канарей", "предзнан", "ии-метк", "снимк", "ai_mark", "canary", "preknowledge"):
        assert word not in dumped.lower()
    # защита пройдена — итог «подтверждено» / «не подтверждено»
    ok = svc.integrity_passport(integ, {"verdict": "confirmed", "label": "Ответ подтверждён устно"}, detailed=True)
    assert ok["verdict"] == "confirmed" and ok["contours"][4]["status"] == "ok"
    bad = svc.integrity_passport(integ, {"verdict": "discrepancies", "label": "Есть расхождения"}, detailed=True)
    assert bad["verdict"] == "discrepancies" and bad["verdict_title"] == "Устная защита: не подтверждено"
    # чистая попытка; старая попытка без l_z — контур «нет данных»
    clean = svc.integrity_passport(_integ(), None, detailed=True)
    assert clean["verdict"] == "clean" and not clean["recommended"] and clean["contours"][1]["status"] == "na"
    assert svc.integrity_passport(None, None, detailed=True) is None
    assert svc.defense_status(True, None)["title"] == "Устная защита рекомендована"
    assert svc.defense_status(True, {"verdict": "confirmed"})["title"] == "Устная защита пройдена: подтверждено"
    assert svc.defense_status(True, {"verdict": "discrepancies"})["title"] == "Устная защита пройдена: не подтверждено"


def _choice_item(pos, code=True):
    return {"position": pos, "format": "choose_fix", "done": True, "canary": False, "skills": ["python"],
            "public": {"stem": f"Задание {pos}: найдите и исправьте ошибку в функции.",
                       "code": "def f(xs):\n    return sum(xs) / len(xs)\n" if code else None,
                       "options": [{"id": 1, "text": "Проверить пустой список"}, {"id": 2, "text": "Ничего"}]},
            "answers": {"1": {"value": 1}}, "x": [1]}


def _fake_ts(items, integ):
    return SimpleNamespace(status=TestSessionStatus.finished, direction_id="backend", claimed_grade_id="middle",
                           result={"state": {"items": items}, "engine_result": {"details": {"integrity": integ}}})


def test_eligible_by_code_when_recommended():
    items = [_choice_item(1, code=False), _choice_item(2), _choice_item(3), {**_choice_item(4), "canary": True}]
    # без рекомендации — как раньше: развёрнутых ответов нет, защищать нечего
    good, reason = cx.eligible(_fake_ts(items, _integ()))
    assert not good and "нет развёрнутых ответов" in reason
    # рекомендована (l_z < −2) — защищаются код и выбранные решения, канарейки — нет
    good, reason = cx.eligible(_fake_ts(items, _integ(lz=-2.5)))
    assert reason is None and [g["position"] for g in good] == [1, 2, 3]
    assert all(g["basis"] == "code" for g in good) and "sum(xs)" in good[1]["code"]
    _, meta = cx.defense_context(_fake_ts(items, _integ(lz=-2.5)), good)
    assert meta["basis"] == "code" and meta["reason"] == "integrity"
    # задания с кодом — в приоритете при лимите
    lim = cx.choice_tasks(_fake_ts(items, _integ("medium")), limit=2)
    assert [g["position"] for g in lim] == [2, 3]


# ------------------------------------------------------------------ 3. API: кандидат и работодатель

@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(get_settings(), "interview_enabled", True)
    monkeypatch.setattr(get_settings(), "interview_engine", "stub")
    return get_settings()


def _mark_suspicious(email="cand@example.com", lz=-2.7):
    from app.modules.auth.models import User

    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == email))
        ts = db.scalars(select(TSession).where(TSession.user_id == uid).order_by(TSession.started_at.desc())).first()
        ts.result["state"]["items"] = [_choice_item(1), _choice_item(2)]
        er = ts.result.setdefault("engine_result", {})
        er.setdefault("details", {})["integrity"] = _integ("medium", lz=lz)
        flag_modified(ts, "result")
        db.commit()
        return str(ts.id)


def test_api_defense_recommended_bridge_and_employer_card(client, on):
    t = candidate_with_category(client)
    ts = _mark_suspicious()
    st = client.get(f"/api/interview/defense/{ts}", headers=H(t)).json()
    assert st["recommended"] and st["eligible"] and st["can_start"] and st["basis"] == "code"
    assert st["why"] == svc.CANDIDATE_WHY and "l_z" not in str(st["integrity"])
    assert st["integrity"]["verdict"] == "recommended" and not st["integrity"]["detailed"]
    assert st["defense_status"]["status"] == "recommended" and st["minutes"] == 3
    r = client.post(f"/api/interview/defense/{ts}", json={"name": "Иван", "consent": True}, headers=H(t))
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        row = db.get(InterviewSession, uuid.UUID(r.json()["id"]))
        assert row.context_meta.get("basis") == "code" and row.context_meta.get("reason") == "integrity"
        assert [x["id"] for x in row.state["ctx"]["tasks"]] == ["t1", "t2"]
    te = employer(client)
    ref = my_ref(client, t)
    d = client.get(f"/api/interview/candidates/{ref}", headers=H(te)).json()
    assert d["recommended"] and "l_z = −2,70" in d["why"] and d["integrity"]["detailed"]
    assert d["defense_status"]["title"] == "Устная защита рекомендована"
    assert {c["id"]: c["status"] for c in d["integrity"]["contours"]}["fit"] == "warn"


def test_api_attempt_without_integrity_not_recommended(client, on):
    from app.modules.auth.models import User

    t = candidate_with_category(client)
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == "cand@example.com"))
        ts = db.scalars(select(TSession).where(TSession.user_id == uid).order_by(TSession.started_at.desc())).first()
        (ts.result.get("engine_result") or {}).get("details", {}).pop("integrity", None)
        flag_modified(ts, "result")
        db.commit()
        sid = str(ts.id)
    d = client.get(f"/api/interview/defense/{sid}", headers=H(t)).json()
    assert d["recommended"] is False and d["why"] is None and d["integrity"] is None and d["basis"] == "answers"


# ------------------------------------------------------------------ 2, 4, 5. интерфейс и документация

def test_frontend_screenshot_combos_without_interrupting_test():
    src = (FRONT / "pages/candidate/Assessment.tsx").read_text(encoding="utf-8")
    assert "export const isScreenshotCombo" in src
    fn = src[src.index("export const isScreenshotCombo"):src.index("export const SCREENSHOT_NOTICE")]
    assert "isPrintScreen(e)" in fn and "e.metaKey" in fn and "e.shiftKey" in fn
    assert 'k === "s"' in fn and '["3", "4", "5"]' in fn and "Digit3" in fn  # Shift+3 на macOS даёт key «#»
    assert "Снимок экрана зафиксирован в журнале достоверности попытки" in src
    handler = src[src.index("const onKey = (e: KeyboardEvent)"):src.index('window.addEventListener("keydown", onKey)')]
    assert "isScreenshotCombo(e)" in handler and "sig.current.printscreen += 1" in handler
    assert "preventDefault" not in handler and "finish" not in handler and "navigate" not in handler


def test_frontend_integrity_badge_five_contours_and_wiring():
    badge = (FRONT / "components/IntegrityBadge.tsx").read_text(encoding="utf-8")
    assert "Паспорт честности попытки (5 контуров)" in badge and "Пройти ${minutes}-минутную устную защиту" in badge
    for title in ("Канарейки и предзнание", "Психометрический индекс l_z", "Стеганографическая ИИ-метка (U+2063)",
                  "Экран и клавиатурная биометрия (фокус, вставка, ритм, скриншоты)",
                  "Камера / устная защита с видеоаватаром"):
        assert title in badge
    assert re.search(r"\\u2063", badge) is None and "\u2063" not in badge  # метка — только в RenderStem (Р27)
    for f in ("pages/candidate/Attempts.tsx", "components/AttemptsCompare.tsx"):
        s = (FRONT / f).read_text(encoding="utf-8")
        assert "IntegrityBadge" in s and 'from "' in s
    for f in ("Compare.tsx", "JuryPanel.tsx"):  # чужая зона — не трогаем
        for p in FRONT.rglob(f):
            assert "IntegrityBadge" not in p.read_text(encoding="utf-8")


def test_docs_antifraud_section6_table():
    doc = (DOCS / "ANTIFRAUD.md").read_text(encoding="utf-8")
    assert "## 6." in doc
    sec = doc[doc.index("### 6.5."):doc.index("## 7.")]
    assert "5 контуров" in sec and "21 сигнал" in sec and "l_z" in sec and "видеоаватар" in sec
    rows = [ln for ln in sec.splitlines() if re.match(r"^\|\s*\d+\s*\|", ln)]
    assert len(rows) == 21
