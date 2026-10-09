"""«Что если» (Н1, И18): какое требование отсекает больше всего подтверждённых кандидатов и сколько вернётся без него.

«Полностью подходят» — кандидат с подтверждённым грейдом (не «предварительно» и не «не подтверждён») в выбранных
категориях подборки, у которого каждый обязательный навык подтверждён тестом (T1), а заявленные формат работы и город
(T0-условия потребности и фильтры версии) подходят. Это те же правила, что у фильтров подборки (ranking.apply_filters):
прогноз «ещё N» совпадает с тем, что покажет новая версия после ослабления.

Порядок выдачи (ярусы обязательного, затем балл match-v1) не меняется: модуль только считает и предлагает новую версию подборки (прежние сохраняются).

Зарплата не отсекает: минимальные ожидания кандидатов скрыты от работодателя и в подбор не входят — поэтому «без вилки
ещё N» не считается (это раскрывало бы скрытые ожидания). Вилку сравниваем только с рыночным диапазоном категории.

Быстро: один пул (выбранные категории + соседние грейды), все варианты — в памяти; результат кэшируется на 2 минуты
с отметкой свежести данных (число и время последних фактов и профилей).
"""
from __future__ import annotations

from collections import OrderedDict
import copy
import json
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.catalog.models import Category
from app.modules.catalog.seed_data import GRADE_LEVEL, GRADES, STACK, category_title
from app.modules.jury import scope as jury_scope
from app.modules.matching import ranking
from app.modules.profiles.facts import load_bundles
from app.modules.profiles.models import CandidateFact, CandidateProfile

THRESHOLD = 5  # «подборка мала»: меньше 5 полностью подходящих подтверждённых
TTL_S = 120
_CACHE: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
_CACHE_MAX = 256
WF_TITLES = {"office": "офис", "hybrid": "гибрид", "remote": "удалённо"}


def selected_categories(req: dict, filters: dict, cats: dict[str, Category]) -> list[str]:
    """Категории версии подборки — то же правило, что в ranking.build_selection."""
    recs = ranking.recommended_categories(req, {}, cats)
    return list(filters.get("categories") or [r["id"] for r in recs if r["relation"] in ("exact", "direction", "all")])


def strict_filters(req: dict, filters: dict) -> dict:
    """Фильтры «полностью подходят»: обязательный стек — T1, T0-условия потребности и фильтры версии."""
    f = ranking.condition_filters(req, {k: v for k, v in filters.items() if k not in ("categories", "relaxation")})
    must = [i["tag"] for i in req.get("stack_required") or []]
    f["stack_t1"] = list(dict.fromkeys(must + list(filters.get("stack_t1") or [])))
    f.pop("min_score", None)  # порог скора — не требование, его не ослабляем и не учитываем
    return f


def _strict(bundles: list, req: dict, filters: dict, cat_ids: list[str]) -> list:
    pool = [b for b in bundles if b.category_id in cat_ids]
    return ranking.apply_filters(pool, strict_filters(req, filters))


def _stamp(db: Session) -> tuple:
    """Отметка свежести данных для кэша: новые факты (тесты, зонды) и изменения профилей сбрасывают его."""
    n, last = db.execute(select(func.count(CandidateFact.id), func.max(CandidateFact.created_at))).one()
    p_n, p_last = db.execute(select(func.count(CandidateProfile.user_id), func.max(CandidateProfile.updated_at))).one()
    return n, str(last), p_n, str(p_last)


def _key(req: dict, filters: dict) -> str:
    sub = {"direction": req.get("direction"), "grade": req.get("grade"),
           "required": [i["tag"] for i in req.get("stack_required") or []],
           "work_format": req.get("work_format"), "work_formats": req.get("work_formats"), "city": req.get("city"),
           "salary_to": req.get("salary_to")}
    return json.dumps([sub, {k: v for k, v in filters.items() if k != "relaxation"}], sort_keys=True, ensure_ascii=False)


def _skill(tag: str) -> str:
    """«Kafka», но «Без «HTML и CSS»» — русское название навыка берём в кавычки."""
    t = STACK.get(tag, (tag,))[0]
    return t if t.isascii() else f"«{t}»"


def _who(grade_title: str) -> str:
    """«ещё 9 подтверждённых Middle», «ещё 2 подтверждённых (Стажёр)», без грейда — просто «подтверждённых»."""
    return "" if not grade_title else grade_title if grade_title.isascii() else f"({grade_title})"


def _many(n: int) -> str:
    return "подтверждённый" if n % 10 == 1 and n % 100 != 11 else "подтверждённых"


def _without_tag(req: dict, filters: dict, tag: str) -> tuple[dict, dict]:
    r, f = copy.deepcopy(req), copy.deepcopy(filters)
    item = next((i for i in r.get("stack_required") or [] if i["tag"] == tag), None)
    if item:
        r["stack_required"] = [i for i in r["stack_required"] if i["tag"] != tag]
        r["stack_desired"] = [*(r.get("stack_desired") or []), {**item, "weight": 0.3, "status": "edited"}]
    for k in ("stack_t1", "stack_any"):
        if f.get(k):
            f[k] = [t for t in f[k] if t != tag] or None
            if f[k] is None:
                f.pop(k)
    return r, f


def _without(req: dict, filters: dict, req_keys: tuple[str, ...], filter_keys: tuple[str, ...]) -> tuple[dict, dict]:
    r, f = copy.deepcopy(req), copy.deepcopy(filters)
    for k in req_keys:
        r[k] = None
        (r.get("evidence") or {}).pop("salary" if k.startswith("salary") else k.rstrip("s"), None)
        (r.get("review") or {}).pop(k.rstrip("s"), None)
    for k in filter_keys:
        f.pop(k, None)
    return r, f


def _salary_note(req: dict, cats: dict[str, Category], cat_ids: list[str]) -> dict | None:
    st = req.get("salary_to")
    exact = f"{req.get('direction')}.{req.get('grade')}"
    c = cats.get(exact) if exact in cat_ids else None
    if not st or not c or not c.market_salary_from:
        return None
    if st >= c.market_salary_from:
        return None
    return {"salary_to": st, "market_from": c.market_salary_from, "market_to": c.market_salary_to,
            "category": c.title,
            "text": f"Верх вилки ниже рыночного диапазона «{c.title}». Кандидатов это не отсекает — их ожидания "
                    "скрыты и в подбор не входят, — но приглашение с такой вилкой чаще отклоняют."}


def _relaxations(req: dict, filters: dict, sf: dict, cat_ids: list[str], neighbours: list[str], g: str | None,
                 bundles: list, in_cats: list) -> list[dict]:
    """Ослабления по одному требованию: новая пара (требования, фильтры, категории) и сколько подтверждённых
    в выбранных категориях это требование отсекает само по себе."""
    def cut(single: dict) -> int:
        return len(in_cats) - len(ranking.apply_filters(in_cats, single))

    out = []

    def add(kind, key, title, action, r2, f2, cut_n, cats=None, criterion=None):
        cats = cats or cat_ids
        if cats != cat_ids:
            f2 = {**f2, "categories": cats}
        out.append({"kind": kind, "key": key, "title": title, "action": action, "req": r2, "filters": f2,
                    "cats": cats, "cut": cut_n, "criterion": criterion or title})

    for tag in sf.get("stack_t1") or []:
        t = _skill(tag)
        r2, f2 = _without_tag(req, filters, tag)
        add("skill", tag, f"Без {t}", f"Перенести {t} в желательные", r2, f2, cut({"stack_t1": [tag]}),
            criterion=STACK.get(tag, (tag,))[0])
    for tag in filters.get("stack_any") or []:
        if tag in (sf.get("stack_t1") or []):
            continue
        t = _skill(tag)
        _r2, f2 = _without_tag(req, filters, tag)
        add("skill", tag, f"Без {t}", f"Убрать фильтр {t}", req, f2, cut({"stack_any": [tag]}),
            criterion=STACK.get(tag, (tag,))[0])
    formats = sf.get("work_formats") or ([sf["work_format"]] if sf.get("work_format") else [])
    if formats:
        r2, f2 = _without(req, filters, ("work_format", "work_formats"), ("work_format", "work_formats"))
        if sf.get("city") and not filters.get("city"):
            r2["city"] = req.get("city")  # город остаётся условием, пока его не сняли отдельно
            f2["city"] = sf["city"]
        fmt = " или ".join(WF_TITLES.get(x, x) for x in formats)
        add("format", "work_format", f"Любой формат вместо «{fmt}»", "Снять условие формата", r2, f2,
            cut({"work_formats": formats}), criterion=f"формат «{fmt}»")
    if sf.get("city"):
        r2, f2 = _without(req, filters, ("city",), ("city",))
        add("city", "city", f"Без условия «город {sf['city']}»", "Снять условие города", r2, f2, cut({"city": sf["city"]}),
            criterion=f"город {sf['city']}")
    for cid in neighbours:
        rel = "ниже" if GRADE_LEVEL[cid.split(".")[1]] < GRADE_LEVEL[g] else "выше"
        add("grade", cid, f"Добавить {category_title(cid)} (грейд {rel})", "Добавить соседний грейд", req, dict(filters),
            len([b for b in bundles if b.category_id == cid]), cats=cat_ids + [cid])
    if filters.get("fsp_only"):
        add("filter", "fsp_only", "Без условия «только с паспортом ФСП»", "Снять фильтр", req,
            {k: v for k, v in filters.items() if k != "fsp_only"}, cut({"fsp_only": True}), criterion="паспорт ФСП")
    if filters.get("experience_min") is not None:
        add("filter", "experience_min", f"Без условия «стаж от {filters['experience_min']:g} лет»", "Снять фильтр",
            req, {k: v for k, v in filters.items() if k != "experience_min"}, cut({"experience_min": filters["experience_min"]}),
            criterion=f"стаж от {filters['experience_min']:g} лет")
    return out


def what_if(db: Session, req: dict, filters: dict | None = None) -> dict:
    """Счётчик «полностью подходят» и варианты ослабления по одному требованию, по убыванию прироста."""
    t0 = time.perf_counter()
    filters = dict(filters or {})
    key = (jury_scope.current(), _key(req, filters), _stamp(db))
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < TTL_S:
        _CACHE.move_to_end(key)
        return {**hit[1], "cached": True, "ms": round(1000 * (time.perf_counter() - t0), 1)}
    out = _compute(db, req, filters)
    _CACHE[key] = (time.monotonic(), out)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return {**out, "cached": False, "ms": round(1000 * (time.perf_counter() - t0), 1)}


def _compute(db: Session, req: dict, filters: dict) -> dict:
    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    cat_ids = selected_categories(req, filters, cats)
    d, g = req.get("direction"), req.get("grade")
    neighbours = []
    if d and g:
        for cid in (f"{d}.{x}" for x in GRADES if abs(GRADE_LEVEL[x] - GRADE_LEVEL[g]) == 1):
            if cid in cats and cid not in cat_ids:
                neighbours.append(cid)
    universe = cat_ids + neighbours
    pool = ranking.visible_pool(db, category_ids=universe)
    loaded = [b for b in load_bundles(db, [p.user_id for p in pool], direction=d, category_ids=universe).values()
              if b.category_id in universe]
    bundles = [b for b in loaded if b.grade_status == "confirmed"]
    # «Junior (предварительно)» — справочно: проходят все требования, но грейд не подтверждён; в приросты не входят
    provisional = [b for b in loaded if b.grade_status == "provisional" and b.category_id in cat_ids]
    in_cats = [b for b in bundles if b.category_id in cat_ids]
    strict = _strict(bundles, req, filters, cat_ids)
    base = len(strict)
    sf = strict_filters(req, filters)
    provisional_full = len(ranking.apply_filters(provisional, sf))
    grade_title = GRADES.get(g, "") if g else ""
    who = _who(grade_title)
    formats = sf.get("work_formats") or ([sf["work_format"]] if sf.get("work_format") else [])
    relax = _relaxations(req, filters, sf, cat_ids, neighbours, g, bundles, in_cats)
    options: list[dict] = []

    def option(kind: str, key: str, title: str, action: str, r2: dict, f2: dict, c2: list[str], cut_n: int,
               text_who: str = who) -> dict | None:
        n = len(_strict(bundles, r2, f2, c2))
        gain = n - base
        if gain <= 0:
            return None
        return {"kind": kind, "key": key, "title": title, "action": action, "cut": cut_n, "gain": gain, "result": n,
                "text": f"{title} — ещё {gain} {_many(gain)} {text_who}".strip(),
                # требования передаём всегда: без них новая версия взяла бы исходные требования потребности,
                # а не требования этой версии (router._make_version)
                "apply": {"requirements": r2, "filters": {**f2, "relaxation": title[:160]}}}

    for x in relax:
        gt = GRADES[x["key"].split(".")[1]] if x["kind"] == "grade" else ""
        o = option(x["kind"], x["key"], x["title"], x["action"], x["req"], x["filters"], x["cats"], x["cut"],
                   _who(gt) if gt else who)
        if o:
            options.append(o)
    if not options and base < THRESHOLD and relax:
        # Ни одно требование по отдельности ничего не даёт — ослабляем жадно по два-три сразу (без смены грейда)
        cur_r, cur_f, cur_c, titles, keys = req, filters, cat_ids, [], []
        for _step in range(3):
            step = _relaxations(cur_r, cur_f, strict_filters(cur_r, cur_f), cur_c, [], g, bundles, in_cats)
            step = [x for x in step if x["key"] not in keys]
            if not step:
                break
            best = max(step, key=lambda x: (len(_strict(bundles, x["req"], x["filters"], x["cats"])), x["cut"]))
            cur_r, cur_f, cur_c = best["req"], best["filters"], best["cats"]
            titles.append(best["title"])
            keys.append(best["key"])
            if len(_strict(bundles, cur_r, cur_f, cur_c)) > base:
                title = titles[0] + "".join(" и " + t[0].lower() + t[1:] for t in titles[1:])
                o = option("combo", "+".join(keys), title, "Ослабить вместе", cur_r, cur_f, cur_c, best["cut"])
                if o:
                    options.append(o)
                break
    cuts = sorted(({"kind": x["kind"], "key": x["key"], "title": x["criterion"], "cut": x["cut"]}
                   for x in relax if x["kind"] != "grade" and x["cut"] > 0), key=lambda c: -c["cut"])[:5]
    options.sort(key=lambda o: (-o["gain"], -o["cut"], o["title"]))
    criteria = [f"грейд подтверждён ({', '.join(category_title(c) for c in cat_ids[:3])}"
                f"{'…' if len(cat_ids) > 3 else ''})"]
    if sf.get("stack_t1"):
        criteria.append("подтверждены тестом: " + ", ".join(STACK.get(t, (t,))[0] for t in sf["stack_t1"]))
    if formats:
        criteria.append("формат: " + " или ".join(WF_TITLES.get(x, x) for x in formats))
    if sf.get("city"):
        criteria.append(f"город {sf['city']} или готов к переезду")
    if sf.get("fsp_only"):
        criteria.append("есть паспорт ФСП")
    if sf.get("experience_min") is not None:
        criteria.append(f"стаж от {sf['experience_min']:g} лет")
    strict_apply = None
    if base and base < len(in_cats):
        sfa = {k: v for k, v in sf.items() if v not in (None, [], False)}
        strict_apply = {"requirements": req, "filters": {**{k: v for k, v in filters.items() if k != "relaxation"}, **sfa,
                                    "confirmed_only": True, "relaxation": "Только полностью подходящие"}}
    return {"strict": base, "confirmed_in_categories": len(in_cats), "threshold": THRESHOLD, "shown": base < THRESHOLD,
            "criteria": criteria, "options": options[:5], "cuts": cuts, "strict_apply": strict_apply,
            "provisional_full": provisional_full,
            "salary": _salary_note(req, cats, cat_ids)}
