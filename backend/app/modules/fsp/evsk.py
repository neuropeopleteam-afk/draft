"""Разряд по ЕВСК для результатов из официальных протоколов ФСП России.

Что считается
-------------
Для записи протокола (место спортсмена или команды на конкретном соревновании) определяется, норматив
какого спортивного звания или разряда соответствует этому месту, и выполнены ли условия, при которых
место засчитывается:

* нормы мест — «Требования и условия их выполнения по виду спорта «спортивное программирование»»
  (Приложение № 24 к приказу Минспорта России от 22.04.2024 № 450, стр. 185–195);
* условия — Положение о ЕВСК (приказ Минспорта России от 03.03.2025 № 173): участников не менее 6
  (п. 29), субъектов РФ на всероссийских соревнованиях не менее 25 % (п. 30) или не менее 6 с повторным
  выполнением (п. 31), на чемпионатах/первенствах федеральных округов — не менее 50 % субъектов округа
  (п. 32.1), этапы Кубка России приравниваются к «другим всероссийским» (п. 34.1), состав судейской
  коллегии по категориям (п. 40.2), минимальный возраст на день начала соревнования.

Данные о соревновании (вид, возрастная группа, число субъектов и участников, судьи) берутся из справок
ФСП к протоколам — ``evsk_data/events.json``; нормы — ``evsk_data/evsk_norms.json``. Оба файла
без персональных данных.

Важно: спортивный разряд присваивает орган власти по представлению федерации. Здесь — только проверка
«норматив выполнен по официальному протоколу», а не «разряд присвоен».
"""
from __future__ import annotations

import json
import math
import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

DATA_DIR = Path(os.environ.get("FSP_EVSK_DATA_DIR") or Path(__file__).with_name("evsk_data"))

RANK_ORDER = ["МСМК", "МС", "КМС", "I", "II", "III", "Iю", "IIю", "IIIю"]
RANK_TITLE = {
    "МСМК": "мастер спорта России международного класса",
    "МС": "мастер спорта России",
    "КМС": "кандидат в мастера спорта",
    "I": "первый спортивный разряд",
    "II": "второй спортивный разряд",
    "III": "третий спортивный разряд",
    "Iю": "первый юношеский спортивный разряд",
    "IIю": "второй юношеский спортивный разряд",
    "IIIю": "третий юношеский спортивный разряд",
}
# Квалификационные категории спортивных судей по убыванию.
JUDGE_LEVELS = ["ВК", "1К", "2К", "3К", "ЮС"]

STATUS_TITLES = {
    "fulfilled": "норматив выполнен",
    "needs_second_result": "нужен повторный результат",
    "conditions_not_met": "условия соревнования не выполнены",
    "no_norm": "место ниже нормативов",
    "unknown": "нет данных о соревновании",
}


@lru_cache(maxsize=1)
def load_norms() -> dict[str, Any]:
    return json.loads((DATA_DIR / "evsk_norms.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _events_file() -> dict[str, Any]:
    p = DATA_DIR / "events.json"
    if not p.exists():
        return {"events": {}, "page_map": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def load_events() -> dict[str, dict[str, Any]]:
    """Соревнования из справок ФСП: ``event_id -> описание`` (без ПДн)."""
    return _events_file().get("events", {})


def event_for_page(pdf_url_or_name: str, page: int | None) -> str | None:
    """Какому соревнованию принадлежит страница PDF (``None`` — справка или страница не протокола)."""
    name = (pdf_url_or_name or "").rsplit("/", 1)[-1]
    for seg in _events_file().get("page_map", {}).get(name, []):
        a, b = seg["pages"]
        if page is not None and a <= int(page) <= b:
            return seg.get("event_id") if seg.get("page_type") == "protocol" else None
    return None


def _parse_range(s: str) -> tuple[int, int]:
    s = str(s).replace("–", "-").strip()
    if "-" in s:
        a, b = s.split("-", 1)
        return int(a), int(b)
    return int(s), int(s)


def _age_on(birth: str | None, on: str | None) -> int | None:
    if not birth or not on:
        return None
    try:
        b = date.fromisoformat(str(birth)[:10])
        d = date.fromisoformat(str(on)[:10])
    except ValueError:
        return None
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))


def _judges_ok(rank: str, judges: dict[str, int] | None) -> tuple[bool | None, str]:
    norms = load_norms()["conditions"]["judges"]
    need = norms.get(rank, {}).get("need")
    if not need:
        return True, "не требуется"
    if not judges:
        return None, "состав судейской коллегии неизвестен"
    have = {k: int(judges.get(k, 0) or 0) for k in JUDGE_LEVELS}
    # Жадная проверка: сначала «точные» требования (ВК), затем «не ниже» — от старшей ступени к младшей,
    # списывая самых младших подходящих судей; один судья не засчитывается дважды.
    exact_vk = need.get("ВК", 0)
    if have["ВК"] < exact_vk:
        return False, f"нужно ВК: {exact_vk}, есть {have['ВК']}"
    used_vk = exact_vk
    remaining = dict(have)
    remaining["ВК"] -= used_vk
    for key in sorted((k for k in need if k.startswith(">=")), key=lambda k: JUDGE_LEVELS.index(k[2:])):
        level = key[2:]
        n = need[key]
        avail = sum(remaining[k] for k in JUDGE_LEVELS[: JUDGE_LEVELS.index(level) + 1])
        if avail < n:
            return False, f"нужно не ниже {level}: {n}, есть {avail}"
        # списываем начиная с самых младших подходящих категорий
        for k in reversed(JUDGE_LEVELS[: JUDGE_LEVELS.index(level) + 1]):
            take = min(remaining[k], n)
            remaining[k] -= take
            n -= take
            if n == 0:
                break
    return True, "выполнено"


def _norm_rank(status: str, age_group: str, discipline: str | None, place: int) -> tuple[str | None, dict | None]:
    norms = load_norms()
    kids = set(norms.get("disciplines_kids", []))
    best: tuple[int, str, dict] | None = None
    for row in norms["rows"]:
        if row["status"] != status or row["age_group"] != age_group:
            continue
        if row.get("kids_only") and discipline and discipline not in kids:
            continue
        for rank, rng in row["places"].items():
            a, b = _parse_range(rng)
            if a <= place <= b:
                k = RANK_ORDER.index(rank)
                if best is None or k < best[0]:
                    best = (k, rank, {**row, "column": rank, "places_range": rng})
    if best is None:
        return None, None
    return best[1], best[2]


def evsk_rank_for(record: dict[str, Any], context: dict[str, Any] | None = None, *,
                  birth_date: str | None = None) -> dict[str, Any]:
    """Проверить запись протокола по ЕВСК. Формат ответа — см. модульную документацию."""
    norms = load_norms()
    ctx = context
    if ctx is None:
        ev_id = record.get("event_id") or event_for_page(record.get("pdf_url", ""), record.get("page"))
        ctx = load_events().get(ev_id or "")
    res: dict[str, Any] = {"rank": None, "status": "unknown", "fulfilled": False, "basis": None,
                           "conditions": [], "pending": [], "explain": ""}
    if not ctx:
        res["explain"] = "Соревнование не размечено по справкам ФСП — проверка по ЕВСК невозможна."
        return res
    status = ctx.get("evsk_status")
    title = ctx.get("title") or ctx.get("competition") or "соревнование"
    if not status:
        res["status"] = "no_norm"
        res["explain"] = f"{title}: документ не является протоколом соревнования, включённого в нормы ЕВСК."
        return res
    try:
        place = int(record.get("place"))
    except (TypeError, ValueError):
        place = 0
    if place < 1:
        res["status"] = "no_norm"
        res["explain"] = f"{title}: место не указано в протоколе."
        return res
    discipline = ctx.get("discipline") or record.get("discipline")
    rank, row = _norm_rank(status, ctx.get("age_group") or "men_women", discipline, place)
    if not rank:
        res["status"] = "no_norm"
        res["explain"] = f"{title}: {place} место — ниже нормативов ЕВСК для этого вида соревнований."
        return res
    res["rank"] = rank
    res["basis"] = {
        "document": norms["documents"]["norms"]["title"],
        "url": norms["documents"]["norms"]["url"],
        "row": f"{norms['statuses'][status]} — {norms['age_groups'][row['age_group']]}",
        "column": rank,
        "places": row["places_range"],
        "page": row["page"],
    }
    cond = norms["conditions"]
    conds: list[dict[str, Any]] = []
    # п. 29 — участников не менее 6
    n_part = ctx.get("participants_total")
    conds.append({"code": "participants", "ok": (None if n_part is None else int(n_part) >= cond["participants_min"]["value"]),
                  "value": n_part, "need": cond["participants_min"]["value"], "basis": cond["participants_min"]["basis"]})
    # п. 30–32 — субъекты РФ
    level = norms["level"][status]
    n_subj = ctx.get("subjects_total")
    second_needed = False
    if level == "allrus":
        need = math.ceil(cond["allrus_subjects_share"]["value"] * cond["subjects_rf_total"]["value"])
        if n_subj is None:
            ok = None
        elif int(n_subj) >= need:
            ok = True
        elif int(n_subj) >= cond["allrus_subjects_fallback_min"]["value"]:
            ok, second_needed = True, True
        else:
            ok = False
        conds.append({"code": "subjects", "ok": ok, "value": n_subj, "need": need,
                      "second_result_required": second_needed,
                      "basis": cond["allrus_subjects_share"]["basis"] + ("; " + cond["allrus_subjects_fallback_min"]["basis"] if second_needed else "")})
    elif level == "fo":
        fo_total = ctx.get("fo_subjects_total")
        need = math.ceil(cond["fo_subjects_share"]["value"] * fo_total) if fo_total else None
        ok = None if (n_subj is None or need is None) else int(n_subj) >= need
        conds.append({"code": "subjects", "ok": ok, "value": n_subj, "need": need, "basis": cond["fo_subjects_share"]["basis"]})
    elif level == "interregional":
        need = cond["interregional_subjects_min"]["value"]
        ok = None if n_subj is None else int(n_subj) >= need
        conds.append({"code": "subjects", "ok": ok, "value": n_subj, "need": need, "basis": cond["interregional_subjects_min"]["basis"]})
    # п. 40.2 — судейская коллегия
    j_ok, j_note = _judges_ok(rank, ctx.get("judges"))
    conds.append({"code": "judges", "ok": j_ok, "value": ctx.get("judges"), "need": cond["judges"].get(rank, {}).get("need"),
                  "note": j_note, "basis": cond["judges"].get(rank, {}).get("basis")})
    # возраст на день начала
    bd = birth_date or record.get("birth_date")
    age = _age_on(bd, ctx.get("date_start") or record.get("date"))
    min_age = norms["min_age"].get(rank)
    conds.append({"code": "age", "ok": (None if age is None else age >= min_age), "value": age, "need": min_age,
                  "basis": norms["min_age_basis"]})
    if rank == "МС":
        conds.append({"code": "prior_rank", "ok": None, "value": None, "need": "КМС", "basis": cond["prior_rank_for_ms"]["basis"]})
    res["conditions"] = conds
    res["pending"] = [c["code"] for c in conds if c["ok"] is None]
    if any(c["ok"] is False for c in conds):
        res["status"] = "conditions_not_met"
    elif second_needed:
        res["status"] = "needs_second_result"
    else:
        res["status"] = "fulfilled"
    res["fulfilled"] = res["status"] == "fulfilled" and not res["pending"]
    res["explain"] = _explain(title, place, rank, res, ctx)
    return res


def _explain(title: str, place: int, rank: str, res: dict[str, Any], ctx: dict[str, Any]) -> str:
    b = res["basis"]
    parts = [f"{title}: {place} место — норматив «{RANK_TITLE[rank]}» ({b['column']}, места {b['places']}; "
             f"Приложение № 24 к приказу Минспорта № 450, стр. {b['page']})."]
    for c in res["conditions"]:
        if c["code"] == "subjects" and c["value"] is not None:
            mark = "выполнено" if c["ok"] else "не выполнено"
            if c.get("second_result_required"):
                mark = "меньше нормы, но не менее 6 — нужен повторный результат в течение трёх лет (п. 31)"
            parts.append(f"Субъектов РФ: {c['value']} (нужно не менее {c['need']}) — {mark}.")
        elif c["code"] == "judges" and c["value"]:
            jd = ", ".join(f"{k} — {v}" for k, v in c["value"].items() if v)
            parts.append(f"Судьи: {jd} — {c['note']}.")
        elif c["code"] == "participants" and c["value"] is not None and not c["ok"]:
            parts.append(f"Участников {c['value']} — меньше 6 (п. 29).")
        elif c["code"] == "age" and c["ok"] is False:
            parts.append(f"Возраст на день начала {c['value']} — меньше {c['need']} лет.")
    if "age" in res["pending"]:
        parts.append("Возраст не проверен: в протоколе нет даты рождения.")
    if "prior_rank" in res["pending"]:
        parts.append("Для звания МС нужен действующий разряд КМС (п. 36).")
    parts.append("Разряд присваивает орган власти по представлению федерации; здесь — проверка по официальному протоколу.")
    return " ".join(parts)


def best_evsk_for_athlete(records: Iterable[dict[str, Any]], *, birth_date: str | None = None) -> dict[str, Any] | None:
    """Лучший результат спортсмена: сначала выполненные нормативы, затем по званию/разряду и свежести."""
    status_rank = {"fulfilled": 0, "needs_second_result": 1, "conditions_not_met": 2, "no_norm": 3, "unknown": 4}
    best = None
    for r in records:
        e = r.get("evsk") or evsk_rank_for(r, birth_date=birth_date)
        key = (status_rank.get(e["status"], 9), RANK_ORDER.index(e["rank"]) if e.get("rank") in RANK_ORDER else 99,
               "" if not r.get("date") else "".join(chr(255 - ord(ch)) for ch in str(r.get("date"))))
        if best is None or key < best[0]:
            best = (key, {**e, "record": {k: r.get(k) for k in ("event_id", "place", "date", "discipline", "pdf_url", "page")}})
    return best[1] if best else None
