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
  over         тест выше порога СЛЕДУЮЩЕГО грейда, σ(1,7·(θ − порог следующего)) ∈ [0, 1] — «сильнее запроса»;
               знак веса не задан заранее: что лучше для запроса работодателя — решают данные разработки
  p_below      риск, что уровень ниже запрошенного, с учётом точности теста: Φ((порог − θ) / SE) ∈ [0, 1] — минус

Веса — ``ltr_weights.json`` рядом (``tools/realdata/ltr_train.py``): попарное логистическое ранжирование только на
мирах разработки бенчмарка, знак весов ограничен (подтверждённый навык и более сильный тест не снижают место; «тест
проверил и не подтвердил» и «предварительно» не повышают). Нормировка: сумма положительных весов = 1, поэтому балл —
«из 100» (минусы вычитаются в тех же единицах).

Стек вакансии — фильтр каскадом (по умолчанию включён, выключатель ``stack_filter_off``): сначала кандидаты, у которых
все обязательные навыки потребности заявлены или подтверждены тестом (или заданием), затем — у кого их не меньше 2/3,
1/2, 1/3, затем остальные. Никого не прячем (подборка не теряется, вчерашний порог «скрыто: N» терял релевантных —
10 % настоящих навыков в резюме не указаны); внутри ступени фильтра место — только балл (тест, задания, ФСП).
Ступени и сколько в каждой — в ответе (meta.stack_filter).

Выключатель всего match-v2 — ``MATCH_V2=0`` (возврат к match-v1.3).
"""
from __future__ import annotations

from functools import lru_cache
import json
import math
import os
from pathlib import Path

VERSION = "match-v2"
FEATURES = ("test", "margin", "fsp", "required", "desired", "probe", "failed", "provisional", "over", "p_below")
POSITIVE = ("test", "margin", "fsp", "required", "desired", "probe")
NEGATIVE = ("failed", "provisional", "p_below")
FREE = ("over",)  # знак веса — из обучения
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
    "over": "Тест выше порога следующего грейда (сильнее запроса)",
    "p_below": "Риск, что уровень ниже запрошенного (с учётом точности теста)",
}
THRESHOLDS = (1.0, 2 / 3, 1 / 2, 1 / 3, 0.0)
K_MIN = 10
WEIGHTS_FILE = Path(__file__).with_name("ltr_weights.json")
# запасные веса — только если файла нет (тесты без артефакта); продукт и бенчмарк читают файл
FALLBACK = {"test": 0.45, "margin": 0.20, "fsp": 0.15, "required": 0.0, "desired": 0.05, "probe": 0.15,
            "failed": -0.45, "provisional": -0.05, "over": 0.0, "p_below": 0.0}


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


def over_of(theta: float | None, next_cut: float | None) -> float:
    """σ(1,7·(θ − порог следующего грейда)); 0 — следующего грейда нет или теста нет."""
    if theta is None or next_cut is None:
        return 0.0
    return round(sigma(1.7 * (float(theta) - float(next_cut))), 4)


def p_below_of(theta: float | None, se: float | None, cut: float | None) -> float:
    """Φ((порог − θ) / SE): вероятность, что истинный уровень ниже порога запрошенного грейда (по точности теста)."""
    if theta is None or cut is None:
        return 0.0
    se = max(0.05, float(se or 0.45))
    return round(0.5 * math.erfc((float(theta) - float(cut)) / (se * math.sqrt(2.0))), 4)


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


def stack_step(cov: float) -> int:
    """Ступень каскада фильтра стека: 0 — все обязательные, 1 — ≥ 2/3, 2 — ≥ 1/2, 3 — ≥ 1/3, 4 — меньше."""
    for j, thr in enumerate(THRESHOLDS[:-1]):
        if cov >= thr - 1e-9:
            return j
    return len(THRESHOLDS) - 1


def stack_filter(scored: list, req: dict, filters: dict, *, first_tier) -> tuple[list, dict]:
    """scored — [(балл, Bundle, comps, reasons)]. Возвращает (те же кандидаты, meta) — каскад, никого не прячет.
    meta["steps"] — ступень каждого кандидата по id(Bundle) (для ключа сортировки; в ответ API не идёт),
    meta["counts"] — сколько кандидатов первого яруса на каждой ступени."""
    tags = required_tags(req)
    meta = {"on": False, "off": bool(filters.get("stack_filter_off")), "tags": tags, "threshold": None,
            "hidden": 0, "k_min": K_MIN, "cascade": True, "counts": {}, "steps": {},
            "rule": "стек вакансии — фильтр каскадом: сначала все обязательные навыки заявлены или подтверждены "
                    "тестом, затем — часть; баллов не даёт"}
    if not tags or meta["off"]:
        return scored, meta
    counts = [0] * len(THRESHOLDS)
    for x in scored:
        j = stack_step(stack_coverage(x[1], tags))
        meta["steps"][id(x[1])] = j
        if first_tier(x[1]):
            counts[j] += 1
    meta.update(on=True, threshold=1.0, counts={"all": counts[0], "partial": sum(counts[1:-1]), "none": counts[-1]})
    return scored, meta


def threshold_text(meta: dict) -> str | None:
    if not meta.get("on"):
        return None
    c = meta.get("counts") or {}
    rest = (c.get("partial") or 0) + (c.get("none") or 0)
    tail = f"; ниже — с частью навыков или без них: {rest}" if rest else ""
    return (f"Сначала — кандидаты, у которых все обязательные навыки заявлены или подтверждены тестом: "
            f"{c.get('all', 0)}{tail}. Фильтр стека баллов не даёт")


def public_meta(meta: dict) -> dict:
    """meta.stack_filter для ответа API — без служебной карты ступеней."""
    return {k: v for k, v in meta.items() if k != "steps"}


def sigma(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))
