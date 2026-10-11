"""«Что сейчас просит рынок» для кандидата (Я12б): частые навыки его категории по вакансиям hh.ru и что из них он ещё
не подтвердил — со ссылкой на тест или короткое задание с автопроверкой.

Источник — агрегат ``data/skills.json`` (доли вакансий, n, дата; ни одной чужой вакансии — FTT.6), только теги
справочника платформы (то, что можно подтвердить тестом или заданием). Статус навыка — как в «Что требуют
работодатели» (assessment.feedback): подтверждён тестом (T1, ≥ 50 %), проверен ниже порога, заявлен (T0), нет данных.
Блок есть только при HH_ENABLED и снимке; иначе None — экран как раньше.
"""
from __future__ import annotations

from app.modules.catalog.seed_data import DIRECTIONS, GRADES, STACK
from app.modules.hh import snapshot
from app.modules.hh.directions import HH_DIRECTIONS

TOP = 8
STATUS_TITLES = {"confirmed": "подтверждён тестом (T1)", "weak": "проверен, результат ниже 50 %",
                 "declared": "заявлен, не подтверждён", "missing": "не подтверждён"}


def _status(bundle, tag: str) -> str:
    f = (getattr(bundle, "skills_t1", None) or {}).get(tag)
    if f is not None:
        return "confirmed" if (f.value or {}).get("score", 0) >= 0.5 else "weak"
    return "declared" if tag in (getattr(bundle, "stack_t0", None) or set()) else "missing"


def _task_tags(direction: str, grade: str | None, tags: list[str]) -> set[str]:
    """Теги, по которым в банке есть задания с автопроверкой для направления и грейда (короткое задание)."""
    if not tags or not grade:
        return set()
    try:
        from app.modules.assignments.bank import coverage_for

        return set(coverage_for(direction, grade, tags)["covered"])
    except Exception:  # банк недоступен — без ссылки на задание, тест остаётся
        return set()


def _dir_title(d: str) -> str:
    return DIRECTIONS.get(d) or HH_DIRECTIONS.get(d, {}).get("title") or d


def block(direction: str | None, grade: str | None, bundle, test_tags: frozenset[str] | set[str]) -> dict | None:
    if not snapshot.enabled() or not direction:
        return None
    s = snapshot.skills_for(direction, grade)
    if not s:
        return None
    top = [x for x in s["top"] if x["tag"] in STACK][:TOP]
    tags = [x["tag"] for x in top]
    task = _task_tags(direction, grade, tags)
    items, todo = [], 0
    for x in top:
        t, st = x["tag"], _status(bundle, x["tag"])
        action = None
        if st != "confirmed":
            todo += 1
            if t in test_tags:
                action = {"kind": "test", "title": "Подтвердить тестом", "href": "/candidate/assessment",
                          "text": "навык проверяется в тесте направления (повтор — по правилам пересдачи)"}
            elif t in task:
                action = {"kind": "task", "title": "Короткое задание", "href": "/candidate/assignments",
                          "text": "задание с автопроверкой по этому навыку — результат попадёт в профиль (T1)"}
            else:
                action = {"kind": "probe", "title": None, "href": None,
                          "text": "заданий на этот навык пока нет — подтвердить можно задачей-зондом работодателя"}
        items.append({"tag": t, "title": STACK[t][0], "share": x["share"], "n": x["n"], "status": st,
                      "status_title": STATUS_TITLES[st], "action": action})
    scope_title = (f"категория {_dir_title(direction)} · {GRADES.get(grade, grade)}"
                   if s["scope"] == "category" else f"направление {_dir_title(direction)}")
    return {"source": "hh.ru", "scope": s["scope"], "scope_title": scope_title, "n": s["n"], "as_of": s["as_of"],
            "items": items, "not_confirmed": todo,
            "note": (f"Доля из {s['n']} вакансий hh.ru ({s['as_of'][8:10]}.{s['as_of'][5:7]}.{s['as_of'][:4]}), где навык "
                     "есть в «Ключевых навыках» или в тексте. Только агрегат: сами вакансии hh.ru на платформе не "
                     "показываются. Навык «подтверждён», если тест или задание набрали по нему не меньше 50 %.")}
