"""Сигнал адресного задания в подборке (К5): одна строка объяснения, на скор и порядок match-v1 не влияет сама по себе.

Результат задания — факт «зонд» (T1) с вердиктом по рубрике; он уже входит в компонент «зонд» (вес 0,05, формула не
менялась). Эта строка только показывает работодателю, чем подтверждено и как давно: дата, итог рубрики или
автопроверки, какие навыки обновлены.
"""
from __future__ import annotations

from app.modules.profiles import freshness as fr

PREFIX = "Задание работодателя: "


def is_assignment_fact(f) -> bool:
    return ((getattr(f, "value", None) or {}).get("origin")) == "assignment"


def reason_for(probes: list) -> dict | None:
    """Строка объяснения по самому свежему заданию кандидата; None, если заданий нет."""
    facts = [f for f in probes if is_assignment_fact(f)]
    if not facts:
        return None
    f = max(facts, key=lambda x: x.created_at.isoformat() if getattr(x, "created_at", None) else "")
    v = f.value or {}
    title = (f.title or "").removeprefix(PREFIX)
    skills = [s for s in (v.get("skills") or [])][:4]
    from app.modules.catalog.seed_data import STACK

    names = ", ".join(STACK.get(t, (t,))[0] for t in skills)
    more = f" и ещё {len(facts) - 1}" if len(facts) > 1 else ""
    text = (f"«{title}» от {fr.date_text(getattr(f, 'created_at', None))}{more}: {v.get('verdict', 'выполнено')}"
            + (f"; проверены навыки: {names}" if names else ""))
    return {"requirement": "Адресное задание", "level": "T1",
            "status": "confirmed" if float(v.get("score") or 0) >= 0.5 else "partial", "text": text}
