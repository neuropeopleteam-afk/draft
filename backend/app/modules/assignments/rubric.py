"""Рубрика адресного задания (К5): критерии и баллы видны работодателю и кандидату до начала и после проверки.

Сумма — 100 баллов. Критерии двух видов:
* auto — считает система по ключам банка, без участия человека: «Верные ответы» и «Покрытие стека»;
* employer — оценивает работодатель по описанным уровням (якоря баллов заданы текстом): «Подход к решению» и
  «Риски и проверка результата» — только если работодатель попросил описать подход (approach_prompt).
Задание без просьбы о подходе проверяется целиком автоматически (70 + 30). Рубрика хранится в задании: изменение
шаблона не меняет ранее выданные задания. Итог по рубрике уходит в факт «зонд» (вес 0,05 в match-v1, формула не менялась);
факты по навыкам остаются результатом автопроверки.
"""
from __future__ import annotations

from app.core.errors import api_error

AUTO_ONLY = [
    {"id": "answers", "kind": "auto", "max": 70, "title": "Верные ответы по заданиям банка",
     "how": "Доля верных ответов, сверка с ключом на сервере без исполнения кода: баллы = 70 × доля верных."},
    {"id": "stack", "kind": "auto", "max": 30, "title": "Покрытие стека задания",
     "how": "Доля проверяемых тегов стека, по которым верно не меньше половины заданий: баллы = 30 × доля тегов."},
]
WITH_APPROACH = [
    {"id": "answers", "kind": "auto", "max": 50, "title": "Верные ответы по заданиям банка",
     "how": "Доля верных ответов, сверка с ключом на сервере без исполнения кода: баллы = 50 × доля верных."},
    {"id": "stack", "kind": "auto", "max": 20, "title": "Покрытие стека задания",
     "how": "Доля проверяемых тегов стека, по которым верно не меньше половины заданий: баллы = 20 × доля тегов."},
    {"id": "approach", "kind": "employer", "max": 20, "title": "Подход к решению",
     "how": "Оценивает работодатель по тексту ответа о подходе.",
     "levels": [{"points": 0, "label": "Ответа нет или он не по теме"},
                {"points": 5, "label": "Общие слова, шагов нет"},
                {"points": 10, "label": "Шаги есть, но без привязки к стеку и ограничениям"},
                {"points": 15, "label": "Шаги по стеку задания, ограничения названы частично"},
                {"points": 20, "label": "Конкретные шаги по стеку, ограничения и компромиссы названы"}]},
    {"id": "risks", "kind": "employer", "max": 10, "title": "Риски и проверка результата",
     "how": "Оценивает работодатель по тексту ответа о подходе.",
     "levels": [{"points": 0, "label": "Рисков и способа проверки нет"},
                {"points": 5, "label": "Назван риск или способ проверки"},
                {"points": 10, "label": "Названы и риски, и как проверить результат"}]},
]
TOTAL = 100
APPROACH_MIN, APPROACH_MAX = 40, 2000


def build(with_approach: bool) -> list[dict]:
    return [dict(c, **({"levels": [dict(x) for x in c["levels"]]} if c.get("levels") else {}))
            for c in (WITH_APPROACH if with_approach else AUTO_ONLY)]


def default_prompt(title: str | None, stack_titles: list[str]) -> str:
    st = ", ".join(stack_titles[:6])
    return (f"Опишите в 5–10 предложениях, как вы подойдёте к рабочей задаче «{title or 'работодателя'}»"
            + (f" на стеке {st}" if st else "")
            + ": какие шаги сделаете, какие риски видите и как проверите, что результат работает. "
              "Не указывайте ФИО, контакты и ссылки на свои профили.")


def of(a) -> list[dict]:
    """Рубрика задания; у заданий, созданных до К5, — только автоматическая."""
    return list(a.rubric) if getattr(a, "rubric", None) else build(False)


def has_employer_part(rubric: list[dict]) -> bool:
    return any(c["kind"] == "employer" for c in rubric)


def auto_points(rubric: list[dict], at, a) -> dict[str, int]:
    """Баллы автоматических критериев по результату попытки."""
    score = float(at.score or 0.0)
    covered = list((a.coverage or {}).get("covered") or [])
    sk = at.skills or {}
    tags = [t for t in covered if t in sk] or list(sk)
    ok = sum(1 for t in tags if float(sk[t].get("score", 0)) >= 0.5)
    share = ok / len(tags) if tags else score
    out = {}
    for c in rubric:
        if c["kind"] == "auto":
            out[c["id"]] = round(c["max"] * (score if c["id"] == "answers" else share))
    return out


def init_result(rubric: list[dict], at, a) -> dict:
    """Результат сразу после автопроверки: авто-баллы есть, баллы работодателя ждут."""
    pts = auto_points(rubric, at, a)
    return {"criteria": [{"id": c["id"], "kind": c["kind"], "max": c["max"],
                          "points": pts.get(c["id"]) if c["kind"] == "auto" else None} for c in rubric],
            "comment": None}


def totals(rubric: list[dict], result: dict | None) -> dict:
    """auto/employer/total и максимумы; total — только когда оценены все критерии."""
    res = {c["id"]: c.get("points") for c in (result or {}).get("criteria", [])}
    a_max = sum(c["max"] for c in rubric if c["kind"] == "auto")
    e_max = sum(c["max"] for c in rubric if c["kind"] == "employer")
    a_pts = sum(res.get(c["id"]) or 0 for c in rubric if c["kind"] == "auto")
    e_done = all(res.get(c["id"]) is not None for c in rubric if c["kind"] == "employer")
    e_pts = sum(res.get(c["id"]) or 0 for c in rubric if c["kind"] == "employer") if e_done and e_max else (None if e_max else 0)
    total = a_pts + (e_pts or 0) if (e_done or not e_max) else None
    return {"auto_points": a_pts, "auto_max": a_max, "employer_points": e_pts, "employer_max": e_max, "total": total,
            "max": a_max + e_max}


def validate_review(rubric: list[dict], scores: dict) -> dict[str, int]:
    """Оценка работодателя: ровно критерии employer, баллы — только из описанных уровней."""
    need = {c["id"]: c for c in rubric if c["kind"] == "employer"}
    if not need:
        raise api_error(409, "no_employer_criteria", "В рубрике этого задания нет критериев для оценки работодателем")
    bad = [k for k in scores if k not in need]
    if bad:
        raise api_error(422, "criterion_unknown", f"Неизвестный критерий: {', '.join(bad)}")
    out: dict[str, int] = {}
    for cid, c in need.items():
        if cid not in scores or scores[cid] is None:
            raise api_error(422, "criterion_missing", f"Оцените критерий «{c['title']}»")
        v = int(scores[cid])
        if v not in {lv["points"] for lv in c["levels"]}:
            raise api_error(422, "criterion_level", f"«{c['title']}»: выберите один из уровней {', '.join(str(lv['points']) for lv in c['levels'])}")
        out[cid] = v
    return out


def apply_review(rubric: list[dict], result: dict, scores: dict[str, int], comment: str | None) -> dict:
    crit = []
    for c in result["criteria"]:
        crit.append({**c, "points": scores[c["id"]]} if c["kind"] == "employer" else c)
    return {**result, "criteria": crit, "comment": (comment or "").strip() or None}


def view(a, at) -> dict:
    """Рубрика с баллами попытки — для кабинетов (до проверки баллов нет, после — авто, после оценки — итог)."""
    rub = of(a)
    res = {c["id"]: c for c in ((at.rubric_result or {}).get("criteria") or [])} if at is not None else {}
    crit = []
    for c in rub:
        r = res.get(c["id"]) or {}
        crit.append({**c, "points": r.get("points")})
    out = {"max": TOTAL, "criteria": crit}
    if at is not None and at.rubric_result:
        out.update(totals(rub, at.rubric_result))
        out["comment"] = at.rubric_result.get("comment")
    return out
