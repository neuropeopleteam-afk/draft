"""Заглушка api.hh.ru для тестов, CI и e2e (HH_STUB=1): ``httpx.MockTransport`` поверх фикстуры.

Клиент тот же (заголовки, кэш, ошибки) — меняется только транспорт. Данные НЕ настоящие:
* ``fixtures/vacancies.json`` — три демо-вакансии в формате ``GET /vacancies/{id}`` (поля сверены с ответом
  настоящего API 10.10.2026: name, description HTML, key_skills, salary_range, experience, work_format,
  work_schedule_by_days, working_hours, employer, area, alternate_url). Тексты написаны для демо, не взяты с hh.ru;
* поиск ``GET /vacancies`` — синтетические вакансии с вилками по ролям, грейдам и городам (детерминированный
  генератор, «модель, не люди»), чтобы «Рынок по hh.ru» показывал медиану, «мало данных» и переход к России.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import random
import re

import httpx

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vacancies.json"
AREAS = {"1": "Москва", "2": "Санкт-Петербург", "88": "Казань"}
# (роль hh, слова в названии, медиана вилки до вычета НДФЛ по грейдам) — порядок величин как у живых вакансий,
# числа синтетические
ROLES = {
    "backend": ("96", "Python-разработчик (backend)", {"intern": 60_000, "junior": 110_000, "middle": 230_000, "senior": 360_000}),
    "frontend": ("96", "Frontend-разработчик (React)", {"intern": 55_000, "junior": 100_000, "middle": 210_000, "senior": 330_000}),
    "qa": ("124", "QA-инженер (тестировщик)", {"intern": 50_000, "junior": 85_000, "middle": 170_000, "senior": 260_000}),
    "data_ml": ("165", "ML-инженер (data)", {"intern": 70_000, "junior": 130_000, "middle": 260_000, "senior": 400_000}),
    "security": ("116", "Специалист по информационной безопасности", {"intern": 55_000, "junior": 95_000, "middle": 190_000, "senior": 300_000}),
}
GRADE_WORD = {"intern": "Стажёр", "junior": "Junior", "middle": "Middle", "senior": "Senior"}
GRADE_EXP = {"intern": "noExperience", "junior": "between1And3", "middle": "between3And6", "senior": "moreThan6"}
EXP_TITLES = {"noExperience": "Нет опыта", "between1And3": "От 1 года до 3 лет", "between3And6": "От 3 до 6 лет",
              "moreThan6": "Более 6 лет"}
PER_AREA = {"1": 48, "2": 30, "88": 4}  # Казань — мало данных: рынок переходит к России


@lru_cache
def fixtures() -> dict[str, dict]:
    return {str(v["id"]): v for v in json.loads(FIXTURES.read_text(encoding="utf-8"))["vacancies"]}


def _salary(rng: random.Random, median: int) -> dict | None:
    v = int(median * rng.uniform(0.7, 1.35) / 5000) * 5000
    kind = rng.random()
    gross = rng.random() < 0.7
    if kind < 0.06:
        return {"from": v // 90, "to": None, "currency": "USD", "gross": gross, "mode": {"id": "MONTH"}}
    if kind < 0.10:
        return {"from": v // 160, "to": v // 140, "currency": "RUR", "gross": gross, "mode": {"id": "HOUR"}}
    if kind < 0.45:
        return {"from": v, "to": None, "currency": "RUR", "gross": gross, "mode": {"id": "MONTH"}}
    if kind < 0.55:
        return {"from": None, "to": v, "currency": "RUR", "gross": gross, "mode": {"id": "MONTH"}}
    return {"from": int(v * 0.85 / 5000) * 5000, "to": int(v * 1.15 / 5000) * 5000, "currency": "RUR", "gross": gross,
            "mode": {"id": "MONTH"}}


@lru_cache
def market_items() -> list[dict]:
    """Синтетические вакансии поиска (по 4 грейда × 5 направлений × 3 города), детерминированно."""
    out, n = [], 91000000
    for d, (role, title, med) in ROLES.items():
        for g, word in GRADE_WORD.items():
            for area, cnt in PER_AREA.items():
                rng = random.Random(f"{d}.{g}.{area}")
                for i in range(cnt):
                    n += 1
                    exp = GRADE_EXP[g] if rng.random() < 0.7 else rng.choice(list(GRADE_EXP.values()))
                    sal = _salary(rng, med[g]) if rng.random() < 0.9 else None
                    out.append({"id": str(n), "name": f"{word} {title}" if rng.random() < 0.75 else title,
                                "area": {"id": area, "name": AREAS[area]},
                                "professional_roles": [{"id": role, "name": "роль"}],
                                "experience": {"id": exp, "name": EXP_TITLES[exp]},
                                "salary_range": sal, "salary": ({k: sal[k] for k in ("from", "to", "currency", "gross")}
                                                                if sal else None),
                                "archived": False, "alternate_url": f"https://hh.ru/vacancy/{n}",
                                "published_at": "2026-10-10T09:00:00+0300", "stub": True})
    return out


_GROUP = re.compile(r"NAME:\(([^)]*)\)")


def _name_groups(text: str) -> list[list[str]]:
    return [[w.strip().strip('"').lower() for w in g.split(" OR ") if w.strip()] for g in _GROUP.findall(text or "")]


def _search(params: httpx.QueryParams) -> dict:
    roles = set(params.get_list("professional_role"))
    exps = set(params.get_list("experience"))
    area = params.get("area") or "113"
    groups = _name_groups(params.get("text") or "")
    items = [v for v in list(fixtures().values()) + market_items()
             if (not roles or {r["id"] for r in v.get("professional_roles") or []} & roles)
             and (area == "113" or (v.get("area") or {}).get("id") == area)
             and (not exps or (v.get("experience") or {}).get("id") in exps)
             and (params.get("only_with_salary") != "true" or v.get("salary_range"))
             and all(any(w in v["name"].lower() for w in g) for g in groups)]
    per, page = min(int(params.get("per_page") or 20), 100), int(params.get("page") or 0)
    chunk = items[page * per:(page + 1) * per]
    return {"items": chunk, "found": len(items), "pages": (len(items) + per - 1) // per, "page": page,
            "per_page": per, "alternate_url": "https://hh.ru/search/vacancy"}


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if request.method != "GET":
        return httpx.Response(405, json={"errors": [{"type": "method_not_allowed"}]})
    m = re.fullmatch(r"/vacancies/(\d+)", path)
    if m:
        v = fixtures().get(m.group(1)) or next((x for x in market_items() if x["id"] == m.group(1)), None)
        if m.group(1) == "90000429":
            return httpx.Response(429, json={"errors": [{"type": "too_many_requests"}]})
        return httpx.Response(200, json=v) if v else httpx.Response(404, json={"errors": [{"type": "not_found"}]})
    if path == "/vacancies":
        return httpx.Response(200, json=_search(request.url.params))
    if path == "/suggests/areas":
        t = (request.url.params.get("text") or "").lower()
        items = [{"id": k, "text": v} for k, v in AREAS.items() if v.lower().startswith(t)]
        return httpx.Response(200, json={"items": items})
    return httpx.Response(404, json={"errors": [{"type": "not_found"}]})


def transport() -> httpx.MockTransport:
    return httpx.MockTransport(handler)
