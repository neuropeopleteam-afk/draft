"""ФСП v2: равные дисциплины/мероприятия, результат, повторное участие и давность."""
from datetime import date
import math

VERSION = "fsp-v2"
POLICY = ("Все дисциплины и типы мероприятий равны. Победитель — 1; призёр — 0,85; "
          "финалист — 0,60; участник — 0,15. Лучший результат даёт 80 % силы паспорта; "
          "остальные соревнования — до 20 % с убывающей отдачей. Первые 12 месяцев вес "
          "полный, далее плавно снижается, но не ниже 70 %. Только подтверждённые результаты (T2).")
RESULT_WEIGHTS = {"winner": 1.0, "prize": 0.85, "finalist": 0.60, "participant": 0.15}


def result_kind(a) -> str:
    explicit = getattr(a, "result_kind", None)
    if explicit in RESULT_WEIGHTS:
        return explicit
    if a.place == 1:
        return "winner"
    if a.place and 1 < a.place <= 3:
        return "prize"
    title = (a.result_title or "").lower()
    if "победител" in title:
        return "winner"
    if "приз" in title:
        return "prize"
    if "финалист" in title or (a.place and a.place <= 10):
        return "finalist"
    return "participant"


def recency(event_date: date | None, today: date) -> float:
    # Отсутствие даты — не повод для штрафа. Будущие даты не получают надбавки.
    if event_date is None:
        return 1.0
    months = max(0.0, (today - event_date).days / 365.25 - 1)
    return 0.7 + 0.3 * math.exp(-months / 3)


RELEVANCE_POLICY = (" Результат по дисциплине, близкой к специализации кандидата, — полный вес; смежной — 0,9; "
                    "дальше — 0,8 (дисциплины между собой равны: у каждой есть близкие специализации).")


def details(achievements, *, today: date | None = None, direction: str | None = None,
            relevance: bool = False) -> dict:
    """Сила паспорта. relevance=True (флаг FSP_DISCIPLINE_RELEVANCE) — вклад результата умножается на коэффициент
    близости дисциплины к направлению кандидата (fsp/relevance.py); при False ответ байт-в-байт прежний (fsp-v2)."""
    from app.modules.fsp import relevance as rel

    today = today or date.today()
    events = {}
    for a in achievements:
        if not a.verified:
            continue
        # Один турнир может иметь несколько дисциплин/записей; повтор импорта не даёт бонус.
        key = getattr(a, "event_id", None) or (a.event_name.strip().casefold(), a.event_date)
        kind = result_kind(a)
        value = RESULT_WEIGHTS[kind] * recency(a.event_date, today)
        c = rel.coef(getattr(a, "discipline", None), direction) if relevance else 1.0
        value *= c
        if key not in events or value > events[key]["value"]:
            events[key] = {"value": value, "result": kind, "discipline": getattr(a, "discipline", None), "coef": c}
    values = sorted((e["value"] for e in events.values()), reverse=True)
    strength = 0.8 * values[0] + 0.2 * (1 - math.exp(-sum(values[1:]))) if values else 0.0
    best = max(events.values(), key=lambda e: e["value"]) if values else None
    out = {"version": VERSION, "strength": round(strength, 3), "competitions": len(values),
           "best_result": best["result"] if best else None,
           "policy": POLICY, "as_of": today.isoformat()}
    if relevance:
        out["policy"] = POLICY + RELEVANCE_POLICY
        out["relevance"] = {"enabled": True, "direction": direction,
                            "best": ({"discipline": best["discipline"], **rel.explain(best["discipline"], direction)}
                                     if best else None)}
    return out
