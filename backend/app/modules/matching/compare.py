"""Сравнение 2–3 кандидатов рядом в контексте потребности.

Строки — требования потребности (каждое — с цитатой из текста работодателя) и подтверждающие факты: категория и
грейд, θ с точностью (± SE, 95 % интервал, вероятность уровня не ниже запрошенного), достоверность результата
теста, каждый навык из потребности (T1 — подтверждён заданиями, T0 — только заявлен, нет данных), опыт и формат
(T0, только фильтр), паспорт ФСП (T2), зонды (T1), ожидания по рынку категории и итоговое соответствие.

Обезличивание как в подборке: только public_ref и обезличенная карточка (profiles.facts.card), с учётом настроек
приватности кандидата. ФИО, контакты и скрытый минимум зарплаты сюда не попадают.
"""
from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ProbeStatus
from app.core.fmt import probe_title, quoted, ru_num
from app.modules.catalog.models import Category
from app.modules.catalog.seed_data import DIRECTIONS, GRADE_LEVEL, GRADES, STACK, category_title
from app.modules.contact.salary import to_net
from app.modules.invitations.models import Invitation, Probe
from app.modules.invitations.service import cooldown_until, profile_by_ref
from app.modules.matching import ranking
from app.modules.matching.models import EmployerNeed, SelectionVersion
from app.modules.profiles.facts import (GRADE_CUTS, card, fmt_count, load_bundles, skill_check_text, skill_confirmed,
                                       skill_evidence_text)
from app.modules.profiles.models import Company

MIN_REFS, MAX_REFS = 2, 3
WF_TITLES = {"office": "офис", "hybrid": "гибрид", "remote": "удалённо", "any": "любой формат"}


def _n(x: float, d: int = 2, sign: bool = False) -> str:
    return ru_num(x, d, sign)  # одно округление и формат с интерфейсом (app.core.fmt, Ф3)


def _rub(v: int | None) -> str:
    return f"{v:,}".replace(",", "\u00a0") + "\u00a0₽" if v else "…"


def _p_at_least(theta: float, se: float, grade: str) -> float:
    z = (GRADE_CUTS[grade] - theta) / max(se, 1e-6)
    return 1 - 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _pct(p: float) -> str:
    return "более 99 %" if p > 0.99 else "менее 1 %" if p < 0.01 else f"{p * 100:.0f} %"


def _quote(item: dict | None) -> str | None:
    ev = (item or {}).get("evidence") or {}
    return ev.get("quote")


def _market_cell(cat: Category | None, req: dict) -> dict:
    if cat is None or not (cat.market_salary_from or cat.market_salary_to):
        return {"level": "market", "status": "neutral", "text": "Нет данных о рынке категории"}
    lo, hi, med = cat.market_salary_from, cat.market_salary_to, cat.market_salary_median
    # рынок — на руки (калькулятор Хабр Карьеры, docs/SALARY_SOURCES.md); вилка потребности сравнивается в том же
    # основании: до вычета НДФЛ по умолчанию, «на руки» — если так сказано в тексте (need_parser.salary_net)
    text = f"Рынок {cat.title}: {_rub(lo)} – {_rub(hi)} на руки" + (f", медиана {_rub(med)}" if med else "")
    sf, st = req.get("salary_from"), req.get("salary_to")
    status = "neutral"
    if sf or st:
        top = to_net(st or sf, "net" if req.get("salary_net") else "gross")
        if top and lo and top < lo:
            status, note = "mismatch", "верх вашей вилки ниже рынка категории — возможен отказ"
        elif med and top and top < med:
            status, note = "partial", "верх вашей вилки ниже медианы рынка"
        elif hi and top and top > hi:
            status, note = "confirmed", "верх вашей вилки выше рынка категории"
        else:
            status, note = "confirmed", "ваша вилка в пределах рынка"
        text += f". {note.capitalize()}"
    return {"level": "market", "status": status, "text": text, "source": cat.market_source}


def _stack_cell(b, tag: str) -> tuple[dict, float | None]:
    f = b.skills_t1.get(tag)
    if skill_confirmed(f):
        sc = float(f.value.get("score", 0))
        multi = len(f.value.get("parts") or {}) > 1  # Ф6 (Н5): тест и задание работодателя — раздельные исходы
        return ({"level": "T1", "status": "confirmed",
                 "text": skill_evidence_text(f) if multi else f"Подтверждено заданиями: {fmt_count(f.value.get('correct'))} из "
                         f"{fmt_count(f.value.get('total'))} ({sc * 100:.0f} %)"}, sc)
    if f is not None:  # проверялось тестом, но ниже порога подтверждения
        sc = float(f.value.get("score", 0))
        return ({"level": "T1", "status": "mismatch", "text": skill_check_text(f)}, sc)
    if tag in b.stack_t0:
        return ({"level": "T0", "status": "declared",
                 "text": "Заявлено кандидатом — в ранжирование не входит, можно проверить зондом"}, None)
    return {"level": "none", "status": "missing", "text": "Нет данных"}, None


def _pts(x: float) -> str:
    """Баллы из 100 с десятичной запятой: 3,1."""
    return f"{abs(x):.1f}".replace(".", ",")


def _balls(x: float) -> str:
    v = round(abs(x), 1)
    return "балл" if v == 1 else "балла" if v != int(v) or 2 <= v % 10 <= 4 and not 12 <= v % 100 <= 14 else "баллов"


def why_pairs(items: list[dict], req: dict) -> list[dict]:
    """«Почему A выше B»: вклад каждого подтверждённого фактора в разницу скоров (в баллах из 100).

    items: [{ref, score, comps, tags{tag: доля подтверждения или 0}, theta, se, fsp, probe}] — в порядке выдачи.
    Разница раскладывается точно: Σ вкладов = разница скоров (с точностью до округления).
    """
    w = dict(ranking.WEIGHTS)
    if not req.get("stack_required"):
        w["test"], w["stack_required"] = w["test"] + w["stack_required"], 0.0
    zones = {z: req.get(z) or [] for z in ("stack_required", "stack_desired")}
    order = sorted(items, key=lambda x: -x["score"])
    out = []
    for a, b in zip(order, order[1:]):
        diff = (a["score"] - b["score"]) * 100
        factors: list[dict] = []
        dt = w["test"] * (a["comps"]["test"] - b["comps"]["test"]) * 100
        if abs(dt) >= 0.05:
            th = (lambda x: f"θ {_n(x['theta'], sign=True)} ± {_n(x['se'])}" if x.get("theta") is not None
                  else "нет теста")
            factors.append({"level": "T1", "points": dt, "label": "тест", "a": th(a), "b": th(b)})
        for zone, label in (("stack_required", "обязательно"), ("stack_desired", "желательно")):
            total = sum(i["weight"] for i in zones[zone]) or 1.0
            for it in zones[zone]:
                ta, tb = a["tags"].get(it["tag"], 0.0), b["tags"].get(it["tag"], 0.0)
                d = w[zone] * it["weight"] / total * (ta - tb) * 100
                if abs(d) >= 0.05:
                    pc = (lambda v: f"{v * 100:.0f} %" if v else "не подтверждено")
                    factors.append({"level": "T1", "points": d, "a": pc(ta), "b": pc(tb),
                                    "label": f"{label} {STACK.get(it['tag'], (it['tag'],))[0]}"})
        df = w["fsp"] * (a["comps"]["fsp"] - b["comps"]["fsp"]) * 100
        if abs(df) >= 0.05:
            fs = (lambda x: f"сила паспорта {_n(x['comps']['fsp'])}" if x["comps"]["fsp"] else "нет подтверждённых")
            factors.append({"level": "T2", "points": df, "label": "ФСП", "a": fs(a), "b": fs(b)})
        dp = w["probe"] * (a["comps"]["probe"] - b["comps"]["probe"]) * 100
        if abs(dp) >= 0.05:
            pr = (lambda x: f"оценка {x['comps']['probe'] * 100:.0f} %" if x["comps"]["probe"] else "нет")
            factors.append({"level": "T1", "points": dp, "label": "зонд", "a": pr(a), "b": pr(b)})
        # «Junior (предварительно)» — −0,05 к скору: подтверждённый выше при прочих равных
        dv = -(a["comps"].get("provisional", 0.0) - b["comps"].get("provisional", 0.0)) * 100
        if abs(dv) >= 0.05:
            pv = (lambda x: "предварительно" if x["comps"].get("provisional") else "подтверждён")
            factors.append({"level": "T1", "points": dv, "label": "грейд", "a": pv(a), "b": pv(b)})
        factors.sort(key=lambda f: -f["points"])
        pro = [f for f in factors if f["points"] > 0][:3]
        con = [f for f in factors if f["points"] < 0][-1:]  # главный фактор в пользу второго
        if diff < 0.5:
            summary = (f"{a['ref']} и {b['ref']} почти равны: разница {_pts(diff)} {_balls(diff)} из 100 — "
                       f"решит зонд")
        else:
            summary = f"{a['ref']} выше {b['ref']} на {_pts(diff)} {_balls(diff)} из 100"
        for f in factors:
            f["text"] = f"{f['label']}: {f['a']} против {f['b']}" if f["points"] > 0 else \
                f"{f['label']}: {f['b']} против {f['a']}"
        text = summary + (": " + "; ".join(f"{f['text']} (+{_pts(f['points'])})" for f in pro) if pro else "")
        if con:
            text += f". В пользу {b['ref']}: {con[0]['text']} (+{_pts(con[0]['points'])} ему)"
        out.append({"higher": a["ref"], "lower": b["ref"], "diff": round(diff, 2), "summary": summary, "text": text,
                    "pro": [{**f, "points": round(f["points"], 2)} for f in pro],
                    "con": [{**f, "points": round(f["points"], 2)} for f in con],
                    "factors": [{**f, "points": round(f["points"], 2)} for f in factors]})
    return out


def default_refs(db: Session, need: EmployerNeed, version: int | None) -> list[str]:
    q = select(SelectionVersion).where(SelectionVersion.need_id == need.id)
    q = q.where(SelectionVersion.version == version) if version else q.order_by(SelectionVersion.version.desc())
    v = db.scalars(q.limit(1)).first()
    return [r["ref"] for r in (v.results if v else [])[:MAX_REFS]]


def _salary_req(lo: int | None, hi: int | None) -> str | None:
    if lo and hi:
        return _rub(lo) if lo == hi else f"{_rub(lo)} – {_rub(hi)}"
    return f"от {_rub(lo)}" if lo else f"до {_rub(hi)}" if hi else None


def compare(db: Session, company: Company, need: EmployerNeed, refs: list[str], version: int | None = None) -> dict:
    sel = None
    if version is not None:
        sel = db.scalar(select(SelectionVersion).where(SelectionVersion.need_id == need.id,
                                                       SelectionVersion.version == version))
    if sel is None:
        sel = db.scalars(select(SelectionVersion).where(SelectionVersion.need_id == need.id)
                         .order_by(SelectionVersion.version.desc()).limit(1)).first()
    req = (sel.requirements if sel else None) or need.requirements or {}
    in_sel = {r["ref"]: r for r in (sel.results if sel else [])}
    profiles = [profile_by_ref(db, r) for r in refs]  # скрытые и без категории → 404
    bundles = load_bundles(db, [p.user_id for p in profiles], direction=req.get("direction"))
    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    want_grade = req.get("grade")
    want_title = (category_title(f"{req['direction']}.{want_grade}") if req.get("direction") and want_grade
                  else GRADES.get(want_grade or "") or DIRECTIONS.get(req.get("direction") or ""))

    rows: list[dict] = [
        {"key": "score", "group": "Итог", "title": "Соответствие потребности",
         "hint": "Только подтверждённое: тест, навыки T1, ФСП T2, зонды. Заявленное (T0) в скор не входит"},
        {"key": "category", "group": "Тест", "title": "Категория и грейд",
         "requirement": want_title,
         "quote": ((req.get("evidence") or {}).get("grade") or {}).get("quote")},
        {"key": "specializations", "group": "Тест", "title": "Оба направления",
         "hint": "Основное и дополнительное подтверждаются разными тестами"},
        {"key": "theta", "group": "Тест", "title": "θ и точность оценки",
         "hint": "θ — уровень по шкале теста, ± SE — стандартная ошибка; интервал — 95 %"},
        {"key": "integrity", "group": "Тест", "title": "Достоверность результата теста"},
    ]
    from app.modules.interview import service as iv  # Я15: строка «Устная защита» — только при флаге
    if iv.enabled():
        rows.append({"key": "defense", "group": "Тест", "title": "Устная защита ответов", "hint": iv.COMPARE_HINT})
    for zone, label in (("stack_required", "Обязательно"), ("stack_desired", "Желательно")):
        for it in req.get(zone) or []:
            rows.append({"key": f"stack:{it['tag']}", "group": label, "title": STACK.get(it["tag"], (it["tag"],))[0],
                         "weight": it.get("weight"), "quote": _quote(it)})
    if req.get("experience_years_min"):
        rows.append({"key": "experience", "group": "Фильтры (T0)", "title": "Опыт",
                     "requirement": f"от {req['experience_years_min']:g} лет",
                     "quote": ((req.get("evidence") or {}).get("experience_years_min") or {}).get("quote")})
    if req.get("work_format"):
        rows.append({"key": "work_format", "group": "Фильтры (T0)", "title": "Формат работы",
                     "requirement": WF_TITLES.get(req["work_format"]),
                     "quote": ((req.get("evidence") or {}).get("work_format") or {}).get("quote")})
    rows += [
        {"key": "fsp", "group": "Паспорт ФСП", "title": "Достижения ФСП",
         "hint": "Только подтверждённые реестром (T2); нет истории — нейтрально, без штрафа"},
        {"key": "probe", "group": "Зонды", "title": "Зонды"},
        {"key": "market", "group": "Рынок", "title": "Ожидания по рынку категории",
         "requirement": _salary_req(req.get("salary_from"), req.get("salary_to")),
         "quote": ((req.get("evidence") or {}).get("salary") or {}).get("quote"),
         "hint": "Рыночный диапазон категории кандидата на руки (калькулятор Хабр Карьеры, 25–75-й перцентиль, "
                 "05.10.2026); скрытый минимум кандидата не показывается никогда"},
    ]

    out_c: list[dict] = []
    why_items: list[dict] = []
    values: dict[str, dict[str, float]] = {}
    for p in profiles:
        b = bundles[p.user_id]
        c = card(b, cats)
        s, comps, reasons = ranking.score_candidate(b, req)
        t0 = b.test.value if b.test else {}
        why_items.append({
            "ref": p.public_ref, "score": s, "comps": comps,
            "theta": t0.get("theta"), "se": t0.get("se"),
            "tags": {it["tag"]: (float(b.skills_t1[it["tag"]].value.get("score", 0))
                                 if skill_confirmed(b.skills_t1.get(it["tag"])) else 0.0)
                     for z in ("stack_required", "stack_desired") for it in req.get(z) or []}})
        cells: dict[str, dict] = {}
        cells["score"] = {"level": "T1", "status": "confirmed", "text": f"{round(s * 100)} из 100",
                          "value": s, "components": comps}
        t = b.test.value if b.test else None
        g = b.grade
        cells["specializations"] = {
            "level": "T1" if any(x["status"] == "confirmed" for x in c["specializations"]) else "T0",
            "status": "neutral",
            "text": "; ".join(
                f"{x['category_title'] or x['direction_title']} ({'основное' if x['is_primary'] else 'дополнительное'}; "
                f"{'подтверждено тестом' if x['confirmed_by'] == 'test' else 'ожидает подтверждения'})"
                for x in c["specializations"]),
        }
        if t:
            rel = ""
            st = "confirmed"
            if want_grade and g and g != want_grade:
                rel = (" — на ступень выше запрошенного" if GRADE_LEVEL[g] > GRADE_LEVEL[want_grade]
                       else " — на ступень ниже запрошенного")
                st = "partial"
            pv = c.get("provisional")
            if pv:  # «Junior (предварительно)»: грейд не подтверждён, но и уровень ниже не доказан
                st = "partial"
                rel += (f"; предварительно — вероятность уровня не ниже Junior {pv.get('p_pct', '—')} % "
                        "(подтверждение — от 80 %)")
            cells["category"] = {"level": "T1", "status": st, "provisional": bool(pv),
                                 "text": f"{category_title(b.category_id)}{rel}; тест "
                                         f"{b.test.created_at:%d.%m.%Y}, {t.get('correct')} из {t.get('answered')} верно"}
            th, se = float(t.get("theta") or 0), float(t.get("se") or 0)
            gref = want_grade or g
            txt = f"θ = {_n(th, sign=True)} ± {_n(se)}; 95 % интервал {_n(th - 1.96 * se, sign=True)} … " \
                  f"{_n(th + 1.96 * se, sign=True)}"
            if gref in GRADE_CUTS and se > 0:
                txt += f"; вероятность уровня не ниже {GRADES[gref]} — {_pct(_p_at_least(th, se, gref))}"
            cells["theta"] = {"level": "T1", "status": "confirmed", "text": txt, "value": th, "theta": th, "se": se}
            integ = c["test"].get("integrity") if c.get("test") else None
            if integ:
                cells["integrity"] = {"level": "T1",
                                      "status": {"high": "confirmed", "medium": "partial"}.get(integ["level"], "mismatch"),
                                      "text": f"{(integ.get('title') or '').capitalize()}"
                                              + (f": {integ['reasons'][0]}" if integ.get("reasons") else ""),
                                      "integrity": integ["level"]}
            else:
                cells["integrity"] = {"level": "none", "status": "neutral", "text": "Нет сведений"}
            if iv.enabled():
                cells["defense"] = iv.compare_cell((c.get("test") or {}).get("defense"))
        else:
            for k in ("category", "theta", "integrity") + (("defense",) if iv.enabled() else ()):
                cells[k] = {"level": "none", "status": "missing", "text": "Нет результата теста"}
            gs = c.get("status") or {}
            if gs.get("status") == "unconfirmed":  # грейд не подтверждён: заявленное (T0) и исход последней попытки
                cells["category"] = {"level": "T0", "status": "unconfirmed", "grade_status": "unconfirmed",
                                     "text": gs.get("text") or "Грейд не подтверждён"}
                at = gs.get("attempt") or {}
                if at.get("theta") is not None:
                    cells["theta"] = {"level": "T0", "status": "unconfirmed",
                                      "text": f"Последняя попытка: θ = {_n(float(at['theta']), sign=True)} ± "
                                              f"{_n(float(at.get('se') or 0))} — грейд не подтверждён, в скор не входит"}
        for zone in ("stack_required", "stack_desired"):
            for it in req.get(zone) or []:
                cell, val = _stack_cell(b, it["tag"])
                if val is not None:
                    cell["value"] = val
                cells[f"stack:{it['tag']}"] = cell
        if req.get("experience_years_min"):
            ey = c.get("experience_years")
            if ey is None:
                cells["experience"] = {"level": "T0", "status": "neutral", "text": "Скрыто кандидатом или не указано"}
            else:
                ok = ey >= float(req["experience_years_min"])
                cells["experience"] = {"level": "T0", "status": "declared" if ok else "mismatch",
                                       "text": f"Заявлено: {ey:g} лет" + ("" if ok else " — меньше требуемого")}
        if req.get("work_format"):
            wf = c.get("work_format")
            if wf is None:
                cells["work_format"] = {"level": "T0", "status": "neutral", "text": "Скрыто кандидатом"}
            else:
                ok = wf in (req["work_format"], "any")
                cells["work_format"] = {"level": "T0", "status": "declared" if ok else "mismatch",
                                        "text": f"Заявлено: {WF_TITLES.get(wf, wf)}" + ("" if ok else " — не совпадает")}
        fsp = c.get("fsp") or {}
        if fsp.get("hidden"):
            cells["fsp"] = {"level": "none", "status": "neutral", "text": "Скрыто кандидатом"}
        elif fsp.get("achievements"):
            a = fsp["achievements"]
            cells["fsp"] = {"level": "T2", "status": "confirmed",
                            "text": a[0]["text"] + (f" и ещё {len(a) - 1}" if len(a) > 1 else "")
                                    + f"; сила паспорта {_n(fsp.get('strength') or 0)}",
                            "value": fsp.get("strength") or 0.0}
        else:
            extra = fsp.get("unverified_count") or 0
            cells["fsp"] = {"level": "none", "status": "neutral",
                            "text": "Истории ФСП нет — нейтрально, без штрафа"
                                    + (f"; заявлено без подтверждения: {extra} — не учитывается" if extra else "")}
        if b.probes_t1:
            best = max(b.probes_t1, key=lambda f: f.value.get("score", 0))
            cells["probe"] = {"level": "T1", "status": "confirmed",
                              "text": f"{quoted(probe_title(best.title, best.value.get('verdict')))} — {best.value.get('verdict', 'оценено')}"
                                      + (f"; всего зондов: {len(b.probes_t1)}" if len(b.probes_t1) > 1 else ""),
                              "value": float(best.value.get("score", 0))}
        else:
            cells["probe"] = {"level": "none", "status": "neutral", "text": "Зондов пока нет"}
        cells["market"] = _market_cell(cats.get(b.category_id or ""), req)
        for k, cell in cells.items():
            if isinstance(cell.get("value"), (int, float)):
                values.setdefault(k, {})[p.public_ref] = float(cell["value"])
        until = cooldown_until(db, company.id, p.user_id)
        last_inv = db.scalars(select(Invitation).where(Invitation.company_id == company.id,
                                                       Invitation.candidate_user_id == p.user_id)
                              .order_by(Invitation.created_at.desc()).limit(1)).first()
        active_probe = db.scalar(select(Probe.id).where(
            Probe.company_id == company.id, Probe.candidate_user_id == p.user_id,
            Probe.status.in_([ProbeStatus.sent, ProbeStatus.viewed])).limit(1))
        hit = in_sel.get(p.public_ref)
        out_c.append({
            "ref": p.public_ref, "category": c.get("category"), "grade": g, "score": s, "components": comps,
            "status": c.get("status"), "claimed": c.get("claimed"),
            "rank_in_selection": hit["rank"] if hit else None, "reasons": reasons, "cells": cells,
            "market_range": c.get("market_range"),
            "can_invite": until is None, "invite_available_at": until.isoformat() if until else None,
            "last_invitation_status": last_inv.status.value if last_inv else None,
            "probe_active": active_probe is not None,
        })
    # Лучшее значение в строке (если кандидаты различаются) — для подсветки
    for k, vals in values.items():
        if len(vals) >= 2 and max(vals.values()) - min(vals.values()) > 1e-9:
            top = max(vals.values())
            for cnd in out_c:
                if abs(vals.get(cnd["ref"], -1e9) - top) < 1e-9:
                    cnd["cells"][k]["best"] = True
    return {
        "need": {"id": str(need.id), "title": need.title, "raw_text": need.raw_text, "requirements": req,
                 "version": sel.version if sel else None},
        "rows": rows, "candidates": out_c, "levels": ranking.LEVELS, "weights": ranking.WEIGHTS,
        "selection_total": len(in_sel),
        "why": why_pairs(why_items, req),
    }
