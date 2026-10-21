"""match-v2 (21.10.2026): место внутри категории — только тест и ФСП; стек вакансии — фильтр и строка объяснения.

Правило экспертов (20.10): категория и фильтр грейда — только по тесту; место в категории — по тесту и ФСП; стек —
фильтр и строка объяснения; самоописание (заявленный стек, грейд, формат, город, вилка) в балл не подмешивается.

Балл — объяснимая линейная модель (вклад каждого признака виден HR, «почему выше соседа» — разность вкладов):

  test         сила результата теста относительно порога запрошенного грейда, σ(1,7·(θ − порог)) ∈ [0, 1]
  margin       запас по шкале теста над порогом, (clip(θ − порог, −1, 3) + 1) / 4 ∈ [0, 1]
  fsp          достижения ФСП (fsp-v3: подтверждено ФСП 1,0, протокол ждёт ФСП 0,5, заявлено 0) ∈ [0, 1]
  required     обязательные навыки вакансии, подтверждённые тестом или заданием (доля по весам) ∈ [0, 1]
  desired      желательные навыки вакансии, подтверждённые тестом или заданием ∈ [0, 1]
  probe        лучший результат короткого задания с вилкой ∈ [0, 1]
  failed       обязательные навыки, которые тест ПРОВЕРИЛ и не подтвердил (доля по весам) ∈ [0, 1] — минус
  provisional  грейд предварительный (у порога) — 0/1, минус

Веса — ``ltr_weights.json`` рядом (``tools/realdata/ltr_train.py``): попарное логистическое ранжирование только на
мирах разработки бенчмарка, знак весов ограничен (подтверждённый навык и более сильный тест не снижают место; «тест
проверил и не подтвердил» и «предварительно» не повышают). Нормировка: сумма положительных весов = 1, поэтому балл —
«из 100» (минусы вычитаются в тех же единицах).

Стек вакансии — фильтр (по умолчанию включён, выключатель ``stack_filter_off``): остаются кандидаты, у которых все
обязательные навыки потребности заявлены или подтверждены тестом; если в первом ярусе (подтверждённый или
предварительный грейд) осталось меньше ``K_MIN`` — порог мягче (2/3, 1/2, 1/3, без фильтра), подборка не теряется.
Фильтр только сужает выдачу и баллов не даёт; сколько скрыто — в ответе (meta.stack_filter).

Выключатель всего match-v2 — ``MATCH_V2=0`` (возврат к match-v1.3).
"""
from __future__ import annotations

from functools import lru_cache
import json
import math
import os
from pathlib import Path

VERSION = "match-v2"
FEATURES = ("test", "margin", "fsp", "required", "desired", "probe", "failed", "provisional")
POSITIVE = ("test", "margin", "fsp", "required", "desired", "probe")
NEGATIVE = ("failed", "provisional")
# Подписи для HR (без жаргона); порядок — как в разложении балла
TITLES = {
    "test": "Результат теста на грейд",
    "margin": "Запас над порогом грейда",
    "fsp": "Достижения ФСП (реестр и протоколы)",
    "required": "Обязательные навыки, подтверждённые тестом",
    "desired": "Желательные навыки, подтверждённые тестом",
    "probe": "Короткие задания работодателей",
    "failed": "Обязательные навыки: тест проверил и не подтвердил",
    "provisional": "Грейд предварительный (у порога)",
}
THRESHOLDS = (1.0, 2 / 3, 1 / 2, 1 / 3, 0.0)
K_MIN = 10
WEIGHTS_FILE = Path(__file__).with_name("ltr_weights.json")
# запасные веса — только если файла нет (тесты без артефакта); продукт и бенчмарк читают файл
FALLBACK = {"test": 0.45, "margin": 0.20, "fsp": 0.15, "required": 0.0, "desired": 0.05, "probe": 0.15,
            "failed": -0.45, "provisional": -0.05}


def enabled() -> bool:
    # WIP (переезд 16): по умолчанию ВЫКЛ, пока нет ltr_weights.json из обучения на мирах разработки
    return os.environ.get("MATCH_V2", "1" if WEIGHTS_FILE.exists() else "0") != "0"


@lru_cache(maxsize=1)
def model() -> dict:
    """{"weights": {...}, "meta": {...}} из ltr_weights.json (нормированные: сумма положительных = 1)."""
    if WEIGHTS_FILE.exists():
        d = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
        return {"weights": {k: float(d["weights"].get(k, 0.0)) for k in FEATURES}, "meta": d.get("meta") or {}}
    return {"weights": dict(FALLBACK), "meta": {"source": "fallback (нет ltr_weights.json)"}}


def weights() -> dict:
    return dict(model()["weights"])


def normalize(w: dict) -> dict:
    """Сумма положительных весов = 1 (балл «из 100»); знак: POSITIVE ≥ 0, NEGATIVE ≤ 0."""
    w = {k: (max(0.0, float(w.get(k, 0.0))) if k in POSITIVE else min(0.0, float(w.get(k, 0.0)))) for k in FEATURES}
    s = sum(w[k] for k in POSITIVE) or 1.0
    return {k: round(w[k] / s, 4) for k in FEATURES}


def margin_of(theta: float | None, cut: float | None) -> float:
    if theta is None or cut is None:
        return 0.0
    x = max(-1.0, min(3.0, float(theta) - float(cut)))
    return round((x + 1.0) / 4.0, 4)


def score(x: dict, w: dict | None = None) -> float:
    w = w or weights()
    return round(sum(w[k] * float(x.get(k) or 0.0) for k in FEATURES), 4)


def contributions(x: dict, w: dict | None = None) -> dict:
    """Вклад каждого признака в балл «из 100» (минусы — отрицательные)."""
    w = w or weights()
    return {k: round(w[k] * float(x.get(k) or 0.0) * 100, 1) for k in FEATURES}


# ---------------------------------------------------------------- стек вакансии — фильтр
def required_tags(req: dict) -> list[str]:
    return [i["tag"] for i in (req.get("stack_required") or []) if i.get("tag")]


def stack_coverage(b, tags: list[str]) -> float:
    """Доля обязательных навыков, которые кандидат заявил или подтвердил тестом (в т.ч. через фреймворк → язык)."""
    if not tags:
        return 1.0
    from app.modules.matching import implied
    from app.modules.profiles.facts import skill_confirmed

    have = 0
    t0 = b.stack_t0
    for t in tags:
        f = b.skills_t1.get(t)
        if t in t0 or skill_confirmed(f) or (f is None and implied.implied_by(b.skills_t1, t) is not None):
            have += 1
    return have / len(tags)


def stack_filter(scored: list, req: dict, filters: dict, *, first_tier) -> tuple[list, dict]:
    """scored — [(балл, Bundle, comps, reasons)]. Возвращает (оставшиеся, meta). first_tier(b) → True для яруса 0."""
    tags = required_tags(req)
    meta = {"on": False, "off": bool(filters.get("stack_filter_off")), "tags": tags, "threshold": None,
            "hidden": 0, "k_min": K_MIN, "rule": "стек вакансии — фильтр: обязательные навыки заявлены или "
                                                 "подтверждены тестом; баллов не даёт"}
    if not tags or meta["off"]:
        return scored, meta
    cov = [stack_coverage(x[1], tags) for x in scored]
    chosen, kept = 0.0, scored
    for thr in THRESHOLDS:
        k = [x for x, c in zip(scored, cov, strict=True) if c >= thr - 1e-9]
        if thr == 0.0 or sum(1 for x in k if first_tier(x[1])) >= K_MIN:
            chosen, kept = thr, k
            break
    meta.update(on=chosen > 0, threshold=round(chosen, 3), hidden=len(scored) - len(kept))
    return kept, meta


def threshold_text(meta: dict) -> str | None:
    if not meta.get("on"):
        return None
    thr = meta["threshold"]
    part = "все обязательные навыки" if thr >= 0.999 else f"не меньше {round(thr * 100)} % обязательных навыков"
    return f"Показаны кандидаты, у которых {part} заявлены или подтверждены тестом; скрыто: {meta['hidden']}"


def sigma(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))
