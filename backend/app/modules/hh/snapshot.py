"""Снимок рынка hh.ru (агрегаты с n и датой) для индекса доверия работодателя и «Что сейчас просит рынок».

Данные — только агрегаты, без единой чужой вакансии (FTT.6), собираются ``tools/realdata/hh_plus.py`` и лежат в
``app/modules/hh/data``:

* ``market_snapshot.json`` — медиана и p25–p75 вилок (на руки) по категории (направление × грейд) и региону, n, дата;
* ``skills.json`` — доля вакансий направления (и категории при n ≥ 10), где навык есть в «Ключевых навыках» или в тексте;
* ``demand.json`` — число вакансий по направлениям (для docs и каталога).

Сеть здесь не нужна (снимок, а не живой запрос): индекс доверия считается на многих экранах, а hh.ru — не чаще
1 запроса/с. Включается флагом HH_ENABLED (как вся интеграция); токен для чтения снимка не нужен.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

from app.core.config import get_settings

DATA = Path(__file__).resolve().parent / "data"
MIN_N = 10                   # меньше вакансий с зарплатой — без вывода о реалистичности вилки
HIGH_X, LOW_X = 2.0, 0.5     # как у рынка Хабр Карьеры (trust.SALARY_HIGH_X / LOW_X), но к p75 / p25 hh.ru
RUSSIA = "113"
# Город (как пишут в вакансии) → регион hh.ru в снимке; остальные — по России
CITY_AREA = {"москва": "1", "санкт-петербург": "2", "спб": "2", "питер": "2", "екатеринбург": "3", "новосибирск": "4",
             "казань": "88"}


def enabled() -> bool:
    return bool(get_settings().hh_enabled)


@lru_cache(maxsize=4)
def _load(name: str) -> dict | None:
    p = DATA / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def market_data() -> dict | None:
    return _load("market_snapshot.json")


def skills_data() -> dict | None:
    return _load("skills.json")


def demand_data() -> dict | None:
    return _load("demand.json")


def _rub(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " ₽"


def _date(iso: str | None) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if iso and len(iso) >= 10 else "—"


def area_of(city: str | None, remote: bool = False) -> str:
    if remote or not city:
        return RUSSIA
    c = " ".join(city.lower().replace("ё", "е").replace("г.", " ").split())
    return CITY_AREA.get(c, RUSSIA)


def market_for(category_id: str | None, city: str | None = None, *, remote: bool = False) -> dict | None:
    """Запись снимка для категории и региона: {n, median, p25, p75, area, area_name, as_of, fallback, …}.
    Регион с n < MIN_N — по России с пометкой; None — категории нет в снимке."""
    snap = market_data()
    if not snap or not category_id:
        return None
    rows = (snap.get("categories") or {}).get(category_id)
    if not rows:
        return None
    want = area_of(city, remote)
    e = rows.get(want)
    fallback = None
    if (e is None or e.get("n", 0) < MIN_N) and want != RUSSIA and rows.get(RUSSIA):
        fallback = {"area": snap["areas"].get(want, city or want), "n": (e or {}).get("n", 0)}
        want, e = RUSSIA, rows[RUSSIA]
    if e is None:
        return None
    return {**e, "area": want, "area_name": snap["areas"].get(want, want), "as_of": snap.get("as_of"),
            "fallback": fallback, "category_id": category_id, "conclusive": e.get("n", 0) >= MIN_N and e.get("median") is not None}


def salary_vs_hh(salary_from: int, salary_to: int, basis: str | None, category_id: str | None,
                 city: str | None = None, *, remote: bool = False) -> dict | None:
    """Реалистичность вилки против рынка hh.ru: {status ok|warn|unknown, conclusive, text, n, median, p25, p75, …}.
    n < MIN_N — без вывода (status unknown, текст «мало данных»). None — снимка или категории нет."""
    from app.modules.catalog.seed_data import category_title
    from app.modules.contact.salary import to_net

    m = market_for(category_id, city, remote=remote)
    if m is None:
        return None
    where = m["area_name"] + (f" (в регионе «{m['fallback']['area']}» мало данных: n = {m['fallback']['n']})"
                              if m["fallback"] else "")
    by = ", грейд — по опыту в вакансии" if m.get("by") == "experience" else ""
    head = f"hh.ru, {category_title(category_id)}{by}, {where}, n = {m['n']}, на {_date(m['as_of'])}"
    base = {"source": "hh.ru", "n": m["n"], "median": m.get("median"), "p25": m.get("p25"), "p75": m.get("p75"),
            "area": m["area_name"], "as_of": m["as_of"], "fallback": m["fallback"], "conclusive": m["conclusive"]}
    if not m["conclusive"]:
        return {**base, "status": "unknown", "text": f"по hh.ru мало данных ({head}) — без вывода"}
    f_net, t_net = to_net(salary_from, basis), to_net(salary_to, basis)
    mid = (f_net + t_net) / 2
    rng = f"медиана {_rub(m['median'])}, p25–p75 {_rub(m['p25'])} – {_rub(m['p75'])} на руки ({head})"
    gross = (basis or "gross") == "gross"
    own = f"вилка {_rub(salary_from)} – {_rub(salary_to)}" + (f" (≈ {_rub(f_net)} – {_rub(t_net)} на руки)" if gross else " на руки")
    if t_net > HIGH_X * m["p75"]:
        return {**base, "status": "warn", "position": "above",
                "text": f"{own}: верх больше чем вдвое выше p75 рынка — так бывает в вакансиях-приманках; рынок: {rng}"}
    if f_net < LOW_X * m["p25"]:
        return {**base, "status": "warn", "position": "below",
                "text": f"{own}: низ меньше половины p25 рынка — заметно ниже рынка; рынок: {rng}"}
    pos = "below" if mid < m["p25"] else "above" if mid > m["p75"] else "inside"
    where_mid = {"below": "ниже p25", "above": "выше p75", "inside": "между p25 и p75"}[pos]
    return {**base, "status": "ok", "position": pos,
            "text": f"{own} в разумных пределах: середина {_rub(int(mid))} — {where_mid}; рынок: {rng}"}


def skills_for(direction: str | None, grade: str | None = None) -> dict | None:
    """Частые навыки по hh.ru: категория (если n ≥ 10), иначе направление. {scope, n, as_of, top: […]}."""
    s = skills_data()
    if not s or not direction:
        return None
    cat = (s.get("categories") or {}).get(f"{direction}.{grade}") if grade else None
    if cat and cat.get("n", 0) >= s.get("min_n_category", MIN_N):
        return {"scope": "category", "category_id": f"{direction}.{grade}", "n": cat["n"], "top": cat["top"],
                "as_of": s.get("as_of"), "method": s.get("method")}
    d = (s.get("directions") or {}).get(direction)
    if not d or not d.get("n"):
        return None
    return {"scope": "direction", "category_id": None, "n": d["n"], "top": d["top"], "as_of": s.get("as_of"),
            "method": s.get("method")}
