"""Мини-тест живой демонстрации: 3 задания банка, адаптивно, только автопроверяемые форматы.

Те же семейства, параметры IRT (a, b, σ) и проверка ответов, что у полного теста (app.modules.assessment.bank_engine),
но: 3 задания блока направления (найти дефект, выбрать исправление, вопрос на понимание — удобно на телефоне,
ответ одним касанием), без контрольных заданий, без записи в TestSession — калибровка банка, экспозиция заданий
и аналитика ФСП не искажаются. Следующее задание — по максимуму информации Фишера в текущей оценке θ (случайно
из трёх лучших, чтобы у соседей по залу были разные задания), оценка θ — EAP с априорным N(0, 1), как в полном тесте.

Три задания — три разных сюжета (Ф3, 08.10): кроме уже выданного семейства не выдаётся и другое семейство того же
сюжета (``same_plot``: тот же тип дефекта или та же тема семейства с общим предметным навыком — например, две
задачи cache-aside, два XSS-экранирования, два ROC-AUC с ничьими).

Ключи хранятся только в state гостя на сервере; наружу — условие, код и варианты (public_view банка). Правильность
по отдельным заданиям не возвращается до конца теста, итог — число верных из 3, θ ± SE и экспресс-категория.
Категория — то же отображение θ → категория, что у полного теста и экспресса (``grades.category_level``): наивысший
грейд с P(θ ≥ порога) ≥ 0,8, за 3 задания — не выше Middle и всегда «предварительно».
"""
from __future__ import annotations

from functools import lru_cache
import secrets
import time
from typing import Any

import numpy as np

from assessment_bank import generate, get_spec
from assessment_bank.psychometrics import PoolItem
from assessment_bank.psychometrics.irt import estimate_theta

from app.core.fmt import theta_round
from app.modules.assessment.bank_engine import SEED_MAX, SEED_MIN, BankEngine, _finite, _pool
from app.modules.assessment.grades import category_level
from app.modules.assessment.skill_map import to_stack_tags
from app.modules.catalog.seed_data import category_title

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
    # Для экспресс-демонстрации на телефоне приоритет — содержательным 1-касательным заданиям без многошаговых расчётов
    mobile_items = [p for p in items if "_fwd_k" not in p.family_id and "_solve_" not in p.family_id]
    base = mobile_items if len(mobile_items) >= 2 * N_ITEMS else items
    own = [p for p in base if p.block == direction]
    return own if len(own) >= 2 * N_ITEMS else own + [p for p in base if p.block == "common"]


def new_state(direction: str) -> dict:
    st = {"engine": ENGINE, "direction": direction, "items": [], "theta": START_THETA, "se": 1.0}
    _issue(st)
    return st


# Навыки-«языки» и общие слова — не сюжет: две задачи на Python ещё не повтор
GENERIC_SKILLS = frozenset({"python", "javascript", "typescript", "sql", "java", "go", "bash", "http", "api",
                            "secure_code_review", "test_design", "test_review"})


@lru_cache(maxsize=512)
def _plot(family_id: str) -> tuple[str, str | None, frozenset[str]]:
    """(тема семейства — второй сегмент family_id, тип дефекта, предметные навыки)."""
    spec = get_spec(family_id)
    parts = family_id.split(".")
    return (parts[1] if len(parts) > 2 else family_id, spec.invariants.defect_type,
            frozenset(spec.skills) - GENERIC_SKILLS)


def same_plot(a: str, b: str) -> bool:
    """Один сюжет: то же семейство, тот же тип дефекта или та же тема с общим предметным навыком."""
    if a == b:
        return True
    (ta, da, sa), (tb, db, sb) = _plot(a), _plot(b)
    return bool(da and da == db) or (ta == tb and bool(sa & sb))


def _issue(st: dict) -> dict | None:
    used = [it["family_id"] for it in st["items"]]
    cands = [p for p in pool(st["direction"]) if not any(same_plot(p.family_id, u) for u in used)]
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
    """Итог мини-теста. Категория — общим отображением θ → категория (grades.category_level): наивысший грейд,
    доказанный с P ≥ 0,8, за 3 задания — не выше Middle и с пометкой «предварительно» (полный тест уточняет)."""
    done = [i for i in st["items"] if i["done"]]
    theta, se = float(st["theta"]), float(st["se"])
    lvl = category_level(theta, se, n_items=len(done))
    g = lvl.grade
    # Без единого верного ответа категории нет: доказательства уровня нет, даже если θ (EAP) с априорным N(0; 1)
    # у самых лёгких заданий осталась у порога. При ≥ 1 верном ответе гарантируется хотя бы «Стажёр (предварительно)».
    if not any(float(i["x"][0]) > 0 for i in done):
        g = "none"
    elif g == "none":
        g = "intern"
    grade = None if g == "none" else g
    theta, se = theta_round(theta, se)  # одно округление θ и погрешности (fmt.theta_round): телефон, зал, подборка
    skills: dict[str, list[float]] = {}
    for i in done:
        for tag in i.get("skills") or []:
            skills.setdefault(tag, []).append(float(i["x"][0]))
    return _finite({
        "engine": ENGINE, "theta": theta, "se": se, "grade": grade,
        "category_id": f"{st['direction']}.{grade}" if grade else None,
        "category_title": f"{category_title(st['direction'] + '.' + grade)} (предварительно)" if grade else None,
        "preliminary": bool(grade), "ceiling": lvl.ceiling, "capped": bool(grade) and lvl.capped,
        "p_grade": lvl.p if grade else None,
        "correct": int(sum(float(i["x"][0]) for i in done)), "answered": len(done),
        "time_s": round(sum(float(i["answers"]["1"]["time_s"]) for i in done), 1),
        "items": [{"position": i["position"], "format": i["format"], "correct": bool(i["x"][0]),
                   "b": round(i["pool"]["b"], 2), "skills": i.get("skills") or []} for i in done],
        "skills": {k: round(sum(v) / len(v), 2) for k, v in skills.items()},
    })
