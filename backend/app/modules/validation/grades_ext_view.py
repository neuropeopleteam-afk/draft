"""Блок /validation «Lead и Principal» (флаг GRADES_EXT_ENABLED): точность различения 6 уровней и что нужно для цели.

Источник — data/grades_ext_need.json (``make grades-ext-need``, симуляция на модельном банке Lead/Principal; модель, не
люди). Здесь только выборка строк для страницы: нынешний банк и правило, отдельные рычаги, сочетание, при котором цель
(точно истинный Lead и Principal ≥ 64 %, завышение ≤ 7 %) достигается, и разброс по реализациям банка. Банк продукта —
``catalog.levels.status()`` (сколько семейств Lead/Principal реально синхронизировано).
"""
from __future__ import annotations

import json
from pathlib import Path

NEED = Path(__file__).resolve().parent / "data" / "grades_ext_need.json"

# (ключ варианта, роль строки) — порядок строк на странице
ROWS = (
    ("base|0.8|top", "now"),
    ("base|0.6|top", "confirm"),
    ("a_x3|0.6|top", "bank"),
    ("c_x2|0.6|top", "partial"),
    ("b_k15_x2|0.6|top", "block"),
    ("d_k20_c_x2_s4|0.8|top", "combo"),
    ("d_k20_c_x2_s4|0.6|top", "goal"),
    ("d_k20_c_x2_s4_p4c16|0.6|top", "goal_more"),
    ("g_k20_x2_s4|0.6|top", "gpcm_goal"),
    ("g_k20_x3_s4_p8c32|0.6|top", "gpcm_more"),
)
ROLE_TITLES = {
    "now": "Сейчас: банк ожидаемый, без блока, развёрнутые 0/1",
    "confirm": "Порог уверенности 0,6 вместо 0,8",
    "bank": "Только банк ×3",
    "partial": "Банк ×2 и частичный балл 0–4",
    "block": "Банк ×2 и блок Lead/Principal (15 заданий)",
    "combo": "Сочетание (банк ×2, коротких ×8, блок 20, частичный балл), порог 0,8",
    "goal": "То же сочетание, порог 0,6",
    "goal_more": "То же и короткие Principal (4 у направления, 16 в общем блоке)",
    "gpcm_goal": "Сочетание «цель», частичный балл — модель платформы (GPCM, шум оценщика)",
    "gpcm_more": "Модель платформы: банк ×3, короткие Principal 8 у направления и 32 в общем блоке",
}
LEVELS = ("senior", "lead", "principal")


def _row(v: dict, role: str) -> dict:
    by = v.get("by_true_level") or {}
    return {"role": role, "title": ROLE_TITLES.get(role, role), "scenario": v.get("text"), "confirm": v.get("confirm"),
            "world": v.get("world"), "n": v.get("n"),
            "levels": {g: {k: by.get(g, {}).get(k) for k in ("n", "exact", "above", "below", "minutes_mean")}
                       for g in LEVELS},
            "above": v.get("above"), "above_ext": v.get("above_ext"), "minutes_mean": v.get("minutes_mean"),
            "goal": bool((by.get("lead") or {}).get("exact", 0) >= 0.64 and (by.get("principal") or {}).get("exact", 0) >= 0.64
                         and v.get("above", 1) <= 0.07)}


def view() -> dict:
    from app.modules.catalog import levels

    out: dict = {"enabled": levels.enabled(), "bank": levels.status() if levels.enabled() else None,
                 "preliminary": bool(levels.enabled() and levels.ext_preliminary("lead"))}
    if not NEED.exists():
        return {**out, "missing": True}
    d = json.loads(NEED.read_text(encoding="utf-8"))
    var = d.get("variants") or {}
    out["rows"] = [_row(var[k], role) for k, role in ROWS if k in var]
    pop = var.get("base|0.8|pop")
    if pop:
        by = pop.get("by_true_level") or {}
        out["population"] = {"n": pop.get("n"), "exact": pop.get("exact"), "above": pop.get("above"),
                             "retest_exact": pop.get("retest_exact"),
                             "levels": {g: {"n": x.get("n"), "exact": x.get("exact")} for g, x in by.items()}}
    rob = []
    groups: dict[tuple, list[dict]] = {}
    for v in var.values():
        groups.setdefault((v.get("scenario"), v.get("confirm"), v.get("world")), []).append(v)
    for k, role in ROWS:
        sc, cf, w = k.split("|")
        vs = groups.get((sc, float(cf), w)) or []
        if len(vs) < 2:
            continue
        lead = [x["by_true_level"]["lead"]["exact"] for x in vs]
        prc = [x["by_true_level"]["principal"]["exact"] for x in vs]
        ab = [x["above"] for x in vs]
        rob.append({"role": role, "title": ROLE_TITLES.get(role, role), "reps": len(vs),
                    "lead": [min(lead), round(sum(lead) / len(lead), 3), max(lead)],
                    "principal": [min(prc), round(sum(prc) / len(prc), 3), max(prc)], "above_max": max(ab),
                    "ok": sum(1 for a, b, c in zip(lead, prc, ab, strict=True) if a >= 0.64 and b >= 0.64 and c <= 0.07),
                    "bank": vs[0].get("bank")})
    out["robustness"] = rob
    out["target"] = d.get("target")
    out["signature"] = d.get("signature")
    return out
