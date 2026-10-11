"""«Почему это задание вам» (К5): причина адресного предложения — слепок на момент выдачи.

Причины по убыванию веса (вес же определяет, какое открытое задание предложить в ленте):
* weak_skill   — навык из стека задания подтверждён слабо (доля верных ниже 50 %): задание даёт шанс подтвердить;
* stale_skill  — навык подтверждался давно (старше 90 дней; старше 180 — вес выше): профиль в этой части устарел;
* declared_only — навык заявлен в опросе, но на платформе не подтверждён;
* need_match   — стек задания пересекается с обязательными требованиями потребности или вакансии работодателя;
* direction    — только то же направление и пересечение стека (нечего подтверждать — свежие сильные навыки).
Каждая строка несёт два текста: для кандидата и нейтральный для работодателя (без «заявлено в опросе»: приватность
заявленного стека остаётся за кандидатом). Тексты не обращаются в LLM: причина должна быть воспроизводима.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.db import as_aware, utcnow
from app.integrations.vacancies.models import Vacancy
from app.modules.assignments.models import Assignment
from app.modules.catalog.seed_data import category_title, tag_title
from app.modules.matching.models import EmployerNeed
from app.modules.profiles import freshness as fr
from app.modules.profiles.facts import fmt_count, load_bundles, skill_confirmed

WEIGHTS = {"weak_skill": 1.0, "stale_skill": 0.6, "stale_hard": 0.9, "declared_only": 0.5, "fresh_skill": 0.1}
NEED_BONUS = 0.3  # совпадение с обязательными требованиями работодателя
GRADE_BONUS = 0.25
KIND_ORDER = {"weak_skill": 0, "stale_skill": 1, "declared_only": 2, "need_match": 3, "direction": 4}
ORIGIN_TITLE = {"test": "в тесте платформы", "assignment": "в задании работодателя"}


def _cap(s: str | None) -> str:
    return (s[:1].upper() + s[1:]) if s else ""


def _title(tag: str) -> str:
    return tag_title(tag)


def requirement_tags(db: Session, a: Assignment) -> tuple[list[str], list[str], str | None]:
    """Обязательные и желательные теги работодателя (потребность или вакансия) и название источника."""
    if a.need_id:
        n = db.get(EmployerNeed, a.need_id)
        if n is not None:
            req = n.requirements or {}
            must = [x["tag"] for x in req.get("stack_required") or [] if x.get("tag")]
            des = [x["tag"] for x in req.get("stack_desired") or [] if x.get("tag")]
            return must, des, n.title
    if a.vacancy_id:
        v = db.get(Vacancy, a.vacancy_id)
        if v is not None:
            return list(v.stack or []), [], v.title
    return [], [], None


def analyse(db: Session, a: Assignment, user_id, now=None, bundle=None) -> dict:
    """Разбор «что в стеке задания у кандидата слабо, давно или не подтверждено» + вес для ленты."""
    now = now or utcnow()
    b = bundle if bundle is not None else load_bundles(db, [user_id], direction=a.direction_id).get(user_id)
    skills = b.skills_t1 if b else {}
    t0 = b.stack_t0 if b else set()
    rows: list[dict] = []
    have = set(skills) | set(t0)
    for tag in a.stack_tags or []:
        f = skills.get(tag)
        title = _title(tag)
        if f is not None:
            v = f.value or {}
            age = max(0, (now - as_aware(f.created_at)).days) if f.created_at else 0
            when = fr.date_text(f.created_at)
            parts = v.get("parts") or {}
            src = ORIGIN_TITLE.get(next(iter(parts)) if len(parts) == 1 else (v.get("origin") or "test"), "в тесте и заданиях")
            cnt = f"{fmt_count(v.get('correct'))} из {fmt_count(v.get('total'))}"
            if not skill_confirmed(f):
                rows.append({"kind": "weak_skill", "tag": tag, "title": title, "weight": WEIGHTS["weak_skill"], "age_days": age,
                             "text": f"{title}: подтверждён слабо — {cnt} верно {src} ({when}). Задание даёт возможность подтвердить навык.",
                             "employer_text": f"навык {title} требует подтверждения"})
            elif age > fr.FRESH_DAYS:
                w = WEIGHTS["stale_hard"] if age > fr.STALE_DAYS else WEIGHTS["stale_skill"]
                rows.append({"kind": "stale_skill", "tag": tag, "title": title, "weight": w, "age_days": age,
                             "text": f"{title}: последний раз подтверждался {fr.age_text(age)} назад ({when}) — навык давно не проверялся.",
                             "employer_text": f"навык {title} давно не подтверждался ({fr.age_text(age)})"})
            else:
                rows.append({"kind": "fresh_skill", "tag": tag, "title": title, "weight": WEIGHTS["fresh_skill"], "age_days": age,
                             "text": f"{title}: подтверждён {fr.age_text(age)} назад ({cnt}).", "employer_text": f"навык {title} подтверждён недавно"})
        elif tag in t0:
            rows.append({"kind": "declared_only", "tag": tag, "title": title, "weight": WEIGHTS["declared_only"], "age_days": None,
                         "text": f"{title}: заявлен в опросе, но на платформе не подтверждён — задание подтвердит его фактом T1.",
                         "employer_text": f"навык {title} не подтверждён на платформе"})
    must, des, source_title = requirement_tags(db, a)
    m_have = [t for t in must if t in have]
    d_have = [t for t in des if t in have]
    need = None
    if must or des:
        need = {"title": source_title, "kind": "vacancy" if a.vacancy_id and not a.need_id else "need",
                "required_total": len(must), "required_have": len(m_have),
                "required_titles": [_title(t) for t in m_have], "desired_titles": [_title(t) for t in d_have]}
    return {"rows": rows, "need": need, "have": sorted(have & set(a.stack_tags or []))}


def target_score(an: dict, a: Assignment, grade_id: str | None) -> float:
    """Вес предложения кандидату: сумма весов причин + бонус совпадения с обязательными требованиями + грейд."""
    s = sum(r["weight"] for r in an["rows"] if r["kind"] != "fresh_skill") + 0.1 * sum(1 for r in an["rows"] if r["kind"] == "fresh_skill")
    need = an["need"]
    if need and need["required_total"]:
        s += NEED_BONUS * need["required_have"] / need["required_total"]
    if grade_id and a.grade_id == grade_id:
        s += GRADE_BONUS
    return round(s, 4)


CONTEXT = {"feed": "Система предлагает адресные задания по вашему стеку",
           "probe": "Работодатель отправил вам это задание лично",
           "vacancy": "Задание прилагается к вакансии, на которую вы откликнулись"}


def build(db: Session, a: Assignment, user, source: str, *, frequency_days: int | None = None) -> dict:
    """Слепок причины предложения: главная причина, остальные строки, связь с потребностью работодателя."""
    an = analyse(db, a, user.id)
    reasons = sorted([r for r in an["rows"] if r["kind"] != "fresh_skill"],
                     key=lambda r: (KIND_ORDER[r["kind"]], -r["weight"], r["tag"]))
    need = an["need"]
    if need:
        have = need["required_have"]
        total = need["required_total"]
        what = "вакансии" if need["kind"] == "vacancy" else "потребности"
        if total:
            titles = ", ".join(need["required_titles"][:4])
            txt = (f"Совпадает с обязательными требованиями {what} «{need['title']}»: в вашем профиле {have} из {total}"
                   + (f" ({titles})" if titles else "") + ".")
            et = f"совпадение с обязательным стеком {what} «{need['title']}»: у кандидата {have} из {total}"
        else:
            txt = f"Стек задания взят из {what} «{need['title']}»."
            et = txt.rstrip(".")
        reasons.append({"kind": "need_match", "tag": None, "title": need["title"], "weight": NEED_BONUS, "age_days": None,
                        "text": txt, "employer_text": et})
    if not reasons:
        fresh = [r["title"] for r in an["rows"] if r["kind"] == "fresh_skill"]
        d = category_title(f"{a.direction_id}.{a.grade_id}")
        reasons.append({"kind": "direction", "tag": None, "title": d, "weight": 0.0, "age_days": None,
                        "text": f"Задание по вашему направлению ({d}); стек пересекается с профилем"
                                + (f": {', '.join(fresh[:4])} уже подтверждены недавно — задание укрепит подтверждение." if fresh else "."),
                        "employer_text": f"то же направление ({d}), стек пересекается с профилем"})
    ctx = CONTEXT.get(source, "")
    if source == "feed" and frequency_days:
        ctx += {7: " раз в неделю", 14: " раз в две недели"}.get(frequency_days, f" раз в {frequency_days} дн.")
    return {"version": 1, "source": source, "context": ctx,
            "primary": {k: reasons[0][k] for k in ("kind", "tag", "title", "text", "employer_text")},
            "reasons": [{k: r.get(k) for k in ("kind", "tag", "title", "text", "employer_text", "age_days")} for r in reasons[:5]],
            "need": need, "frequency_days": frequency_days, "at": utcnow().isoformat()}


def public(w: dict | None, role: str = "candidate") -> dict | None:
    """Представление для кандидата (полные тексты) или работодателя (нейтральные: без «заявлено в опросе»)."""
    if not w:
        return None
    emp = role == "employer"
    pick = (lambda r: r.get("employer_text") or r.get("text")) if emp else (lambda r: r.get("text"))
    ctx = w.get("context") or ""
    if emp:
        ctx = {"feed": "Система предложила задание кандидату сама", "probe": "Вы отправили задание кандидату лично",
               "vacancy": "Задание прилагалось к отклику на вакансию"}.get(w.get("source"), "")
    prim = w.get("primary") or {}
    return {"source": w.get("source"), "context": ctx, "kind": prim.get("kind"),
            "headline": _cap(prim.get("employer_text") or prim.get("text")) if emp else prim.get("text"),
            "reasons": [{"kind": r["kind"], "title": r.get("title"), "text": _cap(pick(r)) if emp else pick(r)}
                        for r in w.get("reasons") or []],
            "need": w.get("need"), "at": w.get("at"),
            "visible_to": "кандидату и работодателю" if not emp else "вам и кандидату"}
