"""Мини-тест живой демонстрации: 3 задания банка, адаптивно, только автопроверяемые форматы.

Те же семейства, параметры IRT (a, b, σ) и проверка ответов, что у полного теста (app.modules.assessment.bank_engine),
но: 3 задания блока направления (найти дефект, выбрать исправление, вопрос на понимание — удобно на телефоне,
ответ одним касанием), без контрольных заданий, без записи в TestSession — калибровка банка, экспозиция заданий
и аналитика ФСП не искажаются. Следующее задание — по максимуму информации Фишера в текущей оценке θ (случайно
из трёх лучших, чтобы у соседей по залу были разные задания), оценка θ — EAP с априорным N(0, 1), как в полном тесте.

Ключи хранятся только в state гостя на сервере; наружу — условие, код и варианты (public_view банка). Правильность
по отдельным заданиям не возвращается до конца теста, итог — число верных из 3, θ ± SE и экспресс-категория.
"""
from __future__ import annotations

from functools import lru_cache
import secrets
import time
from typing import Any

import numpy as np

from assessment_bank import generate, get_spec
from assessment_bank.psychometrics import GradeScale, PoolItem
from assessment_bank.psychometrics.irt import estimate_theta

from app.modules.assessment.bank_engine import SEED_MAX, SEED_MIN, BankEngine, _finite, _pool
from app.modules.assessment.skill_map import to_stack_tags

N_ITEMS = 3
FORMATS = ("mcq_concept", "choose_fix", "find_bug")
MAX_ITEM_TIME_S = 300  # длинные задания (до 7 минут) — не для телефона в зале
START_THETA = 0.5  # как у полного теста при заявленном Middle
TOP_K = 3
ENGINE = "mini-3"
DIRECTIONS = ("backend", "frontend", "data_ml", "qa", "security")


@lru_cache(maxsize=1)
def _checker() -> BankEngine:
    return BankEngine()


def pool(direction: str) -> list[PoolItem]:
    items = [p for p in _pool(1) if not p.canary and p.format in FORMATS and p.time_limit_s <= MAX_ITEM_TIME_S]
    own = [p for p in items if p.block == direction]
    return own if len(own) >= 2 * N_ITEMS else own + [p for p in items if p.block == "common"]


def new_state(direction: str) -> dict:
    st = {"engine": ENGINE, "direction": direction, "items": [], "theta": START_THETA, "se": 1.0}
    _issue(st)
    return st


def _issue(st: dict) -> dict | None:
    used = {it["family_id"] for it in st["items"]}
    cands = [p for p in pool(st["direction"]) if p.family_id not in used]
    if not cands:
        return None
    target = float(st["theta"])
    cands.sort(key=lambda p: -float(p.information(target)))
    pi = cands[secrets.randbelow(min(TOP_K, len(cands)))]
    spec = get_spec(pi.family_id)
    seed = SEED_MIN + secrets.randbelow(SEED_MAX - SEED_MIN)
    v = generate(pi.family_id, seed)
    pv = v.public_view()
    it = {
        "token": secrets.token_urlsafe(9), "position": len(st["items"]) + 1, "family_id": pi.family_id,
        "seed": seed, "variant_id": v.variant_id, "format": spec.format, "block": pi.block,
        "skills": to_stack_tags(spec.direction, spec.skills), "language": spec.language,
        "time_limit_s": spec.time_limit_s, "issued_at": time.time(), "parts": 1,
        "pool": {"a": float(np.mean(pi.a_eff)), "b": float(np.mean(pi.b))},
        "public": {"stem": pv["stem"], "code": pv["code"], "options": pv["options"], "steps": [],
                   "code_lines": len((pv["code"] or "").splitlines())},
        "key": v.answer_key.model_dump(include={"kind", "value", "accept"}),
        "answers": {}, "x": [None], "done": False,
    }
    st["items"].append(it)
    return it


def current(st: dict) -> dict | None:
    return next((it for it in st["items"] if not it["done"]), None)


def public_item(st: dict) -> dict | None:
    """Текущее задание без ключа: условие, код, варианты, тип ответа, номер из 3."""
    it = current(st)
    if it is None:
        return None
    kind = BankEngine._answer_kind(it, 1)
    return {"token": it["token"], "position": it["position"], "total": N_ITEMS, "format": it["format"],
            "block": it["block"], "stem": it["public"]["stem"], "code": it["public"]["code"],
            "language": it.get("language"), "options": BankEngine._step_options(it, 1), "answer_kind": kind,
            "time_limit_s": it["time_limit_s"]}


def answer(st: dict, token: str, value: Any) -> bool | None:
    """Принять ответ на текущее задание. None — ответ не принят (не то задание или пустой ответ)."""
    it = current(st)
    if it is None or it["token"] != token:
        return None
    eng = _checker()
    kind = BankEngine._answer_kind(it, 1)
    v = eng._validate(it, 1, kind, value)
    if v is None:
        return None
    it["answers"]["1"] = {"value": v, "time_s": round(max(0.0, time.time() - it["issued_at"]), 1)}
    eng._score(it)
    it["done"] = True
    xs = [float(i["x"][0]) for i in st["items"] if i["done"]]
    est = estimate_theta(np.asarray(xs), np.asarray([i["pool"]["a"] for i in st["items"] if i["done"]]),
                         np.asarray([i["pool"]["b"] for i in st["items"] if i["done"]]), method="eap",
                         prior_sd=1.0)
    st["theta"], st["se"] = round(float(est.theta), 3), round(float(est.se), 3)
    if len(xs) < N_ITEMS:
        _issue(st)
    return True


def finished(st: dict) -> bool:
    done = [i for i in st["items"] if i["done"]]
    return len(done) >= N_ITEMS or (current(st) is None and bool(done))


def result(st: dict) -> dict:
    """Итог мини-теста. Грейд — точечный по θ (пороги шкалы банка), с честной пометкой «экспресс»."""
    done = [i for i in st["items"] if i["done"]]
    theta, se = float(st["theta"]), float(st["se"])
    g = GradeScale().point(theta)
    # Без единого верного ответа категории нет: при 3 заданиях θ (EAP) с априорным N(0; 1) у самых лёгких заданий
    # может остаться у порога Junior, но доказательства уровня нет
    if not any(float(i["x"][0]) > 0 for i in done):
        g = "none"
    grade = None if g == "none" else g
    skills: dict[str, list[float]] = {}
    for i in done:
        for tag in i.get("skills") or []:
            skills.setdefault(tag, []).append(float(i["x"][0]))
    return _finite({
        "engine": ENGINE, "theta": round(theta, 2), "se": round(se, 2), "grade": grade,
        "category_id": f"{st['direction']}.{grade}" if grade else None,
        "correct": int(sum(float(i["x"][0]) for i in done)), "answered": len(done),
        "time_s": round(sum(float(i["answers"]["1"]["time_s"]) for i in done), 1),
        "items": [{"position": i["position"], "format": i["format"], "correct": bool(i["x"][0]),
                   "b": round(i["pool"]["b"], 2), "skills": i.get("skills") or []} for i in done],
        "skills": {k: round(sum(v) / len(v), 2) for k, v in skills.items()},
    })
