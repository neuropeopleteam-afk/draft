"""Релевантность дисциплины ФСП специализации кандидата (ответ организаторов E08, 07.10.2026).

Организаторы: «все дисциплины одинаково приоритетны», но «можно учитывать актуальность спортивного направления:
специалист по ИБ с соревнованиями по ИБ релевантнее, чем с соревнованиями по робототехнике». Отсюда правила:

* **Дисциплины между собой равны.** Коэффициент зависит только от пары «дисциплина — специализация кандидата»,
  ни одна дисциплина не получает преимущества сама по себе: у каждой есть специализации, где она «близко».
* **Мягкий коэффициент.** Близко — 1,0; смежно — 0,9; дальше — 0,8. Он умножает вклад отдельного результата в силу
  паспорта (fsp/rating.details), поэтому даже самый «далёкий» кубок даёт не меньше 80 % своего веса, а на итоговый
  скор подбора влияет не больше чем на 0,10 × 0,2 = 0,02.
* **За флагом** ``FSP_DISCIPLINE_RELEVANCE`` (core/config.Settings.fsp_discipline_relevance): по умолчанию выключено,
  порядок выдачи match-v1 не меняется; включение — только без падения метрик бенчмарка (см. docs/ARCHITECTURE.md).
* Направления платформы: backend, frontend, data_ml, qa, security (catalog.seed_data.DIRECTIONS). Для робототехники и
  БАС своего направления в MVP нет: ближе всего Data/ML (зрение, управление) и Backend (встроенная логика, протоколы).
"""
from __future__ import annotations

CLOSE, NEAR, FAR = 1.0, 0.9, 0.8
TITLES = {CLOSE: "близко к специализации", NEAR: "смежно со специализацией", FAR: "дальше от специализации"}

# дисциплина → {направление: коэффициент}; не перечисленные направления — NEAR (смежно)
AFFINITY: dict[str, dict[str, float]] = {
    "algorithmic": {"backend": CLOSE, "data_ml": CLOSE},
    "product": {"backend": CLOSE, "frontend": CLOSE, "qa": CLOSE},
    "security": {"security": CLOSE, "backend": NEAR, "qa": NEAR, "frontend": FAR, "data_ml": FAR},
    "robotics": {"data_ml": CLOSE, "backend": NEAR, "qa": NEAR, "frontend": FAR, "security": FAR},
    "uav": {"data_ml": CLOSE, "backend": NEAR, "qa": NEAR, "frontend": FAR, "security": FAR},
}


def coef(discipline: str | None, direction: str | None) -> float:
    """Коэффициент релевантности 0,8..1,0; неизвестная дисциплина или направление — 1,0 (без штрафа)."""
    if not discipline or not direction or discipline not in AFFINITY:
        return CLOSE
    return AFFINITY[discipline].get(direction, NEAR)


def title(c: float) -> str:
    return TITLES.get(round(c, 2), "")


def explain(discipline: str | None, direction: str | None) -> dict:
    """{coef, title}; без направления или для неизвестной дисциплины — коэффициент 1,0 и пустая подпись (не утверждаем
    «близко», когда сравнивать не с чем)."""
    c = coef(discipline, direction)
    known = bool(discipline and direction and discipline in AFFINITY)
    return {"coef": c, "title": title(c) if known else ""}


def every_discipline_is_close_somewhere() -> bool:
    """Инвариант «дисциплины равны»: у каждой дисциплины есть направление с коэффициентом 1,0 (проверяется тестом)."""
    return all(CLOSE in d.values() for d in AFFINITY.values())
