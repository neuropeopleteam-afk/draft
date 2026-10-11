"""Свежесть профиля (К5): когда в последний раз подтверждён каждый навык T1 — тестом или заданием работодателя.

Свежесть не входит в формулу подбора match-v1 и порядок выдачи не меняет: это объяснение «насколько давно
подтверждено», видимое кандидату (что стоит обновить) и работодателю (как давно проверено то, что он читает в карточке).
Пороги заданы заранее и на данных не подбирались: до 90 дней — «свежо», 91–180 — «стареет», дальше — «давно».
Дату подтверждения навыка даёт самый поздний из его фактов T1 (merge_skill берёт максимум created_at): новое задание
работодателя обновляет дату у всех навыков своего стека, результат ниже 50 % навык не подтверждает, но дату обновляет.
"""
from __future__ import annotations

from datetime import datetime

from app.core.db import as_aware, utcnow
from app.modules.catalog.seed_data import tag_title

FRESH_DAYS = 90
STALE_DAYS = 180
LEVEL_FRESH, LEVEL_PARTIAL = 0.7, 0.4  # доля свежих подтверждённых навыков: «свежий» / «частично устарел»
LEVEL_TITLES = {"fresh": "Свежий", "aging": "Частично устарел", "stale": "Давно не обновлялся", "none": "Подтверждений нет"}
STATE_TITLES = {"fresh": "свежо", "aging": "стареет", "stale": "давно"}


def state_of(age_days: int) -> str:
    return "fresh" if age_days <= FRESH_DAYS else "aging" if age_days <= STALE_DAYS else "stale"


def age_text(days: int) -> str:
    """«12 дн.», «около 3 мес.» — для объяснений."""
    if days <= 45:
        return f"{days} дн."
    return f"около {round(days / 30)} мес."


def date_text(dt: datetime | None) -> str:
    return as_aware(dt).strftime("%d.%m.%Y") if dt else "—"


def skill_rows(skills: dict, now: datetime | None = None) -> list[dict]:
    """По навыкам T1 (слитые факты Bundle.skills_t1): дата подтверждения, возраст, состояние, подтверждён ли."""
    now = now or utcnow()
    out = []
    for tag, f in skills.items():
        at = getattr(f, "created_at", None)
        if at is None:
            continue
        age = max(0, (now - as_aware(at)).days)
        v = f.value or {}
        score = float(v.get("score") or 0)
        out.append({"tag": tag, "title": tag_title(tag), "score": score, "confirmed": score >= 0.5,
                    "correct": v.get("correct"), "total": v.get("total"), "at": as_aware(at).isoformat(),
                    "date": date_text(at), "age_days": age, "state": state_of(age),
                    "origins": sorted((v.get("parts") or {v.get("origin") or "test": 1}).keys())})
    return sorted(out, key=lambda r: (-r["age_days"], r["tag"]))


def summary(skills: dict, now: datetime | None = None, limit: int = 12) -> dict:
    """Сводка свежести по навыкам T1 одного направления."""
    rows = skill_rows(skills, now)
    n = len(rows)
    fresh = sum(1 for r in rows if r["confirmed"] and r["state"] == "fresh")
    share = round(fresh / n, 3) if n else 0.0
    level = "none" if not n else "fresh" if share >= LEVEL_FRESH else "aging" if share >= LEVEL_PARTIAL else "stale"
    last = max((r["at"] for r in rows), default=None)
    oldest = max(rows, key=lambda r: r["age_days"], default=None)
    text = ("Навыков с подтверждением на платформе пока нет" if not n else
            f"Подтверждено за последние {FRESH_DAYS} дней: {fresh} из {n} навыков"
            + (f"; давнее всего — {oldest['title']} ({age_text(oldest['age_days'])})" if oldest and oldest["state"] != "fresh" else ""))
    return {"level": level, "title": LEVEL_TITLES[level], "n": n, "fresh": fresh, "share_fresh": share,
            "aging": sum(1 for r in rows if r["state"] == "aging"), "stale": sum(1 for r in rows if r["state"] == "stale"),
            "weak": sum(1 for r in rows if not r["confirmed"]), "last_confirmed_at": last, "text": text,
            "fresh_days": FRESH_DAYS, "stale_days": STALE_DAYS, "skills": rows[:limit]}
