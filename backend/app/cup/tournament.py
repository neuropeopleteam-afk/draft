"""Н5: «Отборочный турнир ФСП под вакансию» — Кубок компании × ФСП из потребности работодателя.

Из потребности (/employer/needs/<id>) одним действием создаётся кубок с автопроверкой по дисциплине ФСП
«Продуктовое программирование»:

* три задания банка (403 семейства) под обязательный стек потребности: семейства с однозначным ключом
  (tasks.AUTO_FORMATS, без канареек), допустимые для стека (тот же фильтр технологий, что в тесте), ранжируются по
  совпадению навыков с обязательным стеком, затем с желательным и по грейду; три разных формата по возможности.
  Выбор детерминирован — один и тот же «паспорт задачи» при повторе;
* приз — «Прямой оффер в компанию с подтверждённой вилкой из потребности для топ-5 призёров + очки в рейтинг ФСП»:
  вилка берётся из потребности (основание — «на руки», если так указано), без вилки — рынок категории (это видно
  в паспорте); приглашения получают пять лучших (invite_top_n = 5), места пишутся в паспорт ФСП как мероприятие
  платформы (T1) и учитываются в рейтинге;
* «Паспорт соревновательной задачи ФСП» (passport) — дисциплина, стек, задания с форматами и навыками, приз,
  вилка и её источник; хранится в ``Cup.summary["tournament"]`` и переживает подведение итогов;
* повторный запуск по той же потребности, пока турнир не завершён, возвращает его же (без дублей).

Для демо-компаний (жюри) турнир сразу получает «статистов» — демо-кандидатов категории с результатами автопроверки:
таблица и приглашение призёра в один клик видны без ожидания (места и приглашения есть, фактов T1 и записей паспорта —
нет, как в остальных демо-кубках: service.credits).
"""
from __future__ import annotations

from datetime import timedelta
import random
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.db import utcnow
from app.core.errors import api_error
from app.cup import service as svc
from app.cup import tasks as auto
from app.cup.models import Cup, CupEntry
from app.modules.auth.models import User
from app.modules.catalog.models import Category
from app.modules.catalog.seed_data import category_title, tag_title
from app.modules.contact.salary import basis_title
from app.modules.invitations import service as inv_svc
from app.modules.invitations.models import Invitation
from app.modules.matching.models import EmployerNeed
from app.modules.profiles.models import Company

KIND = "fsp_need_tournament"
DISCIPLINE = "Продуктовое программирование"
TASKS_N = 3
TOP_N = 5
DURATION_DAYS = 7
TIME_LIMIT_MIN = 25
BASE_DIRECTIONS = ("backend", "frontend", "data_ml", "qa", "security")
CUP_GRADES = ("intern", "junior", "middle", "senior")
FORMAT_TITLES = {"find_bug": "Найти строку с дефектом", "predict_output": "Предсказать вывод",
                 "choose_fix": "Выбрать исправление", "mcq_concept": "Вопрос с выбором ответа"}
# близкие теги: требование «PostgreSQL» закрывают и семейства по SQL, «FastAPI» — по Python, HTTP и REST
RELATED = {"postgresql": {"sql"}, "mysql": {"sql"}, "clickhouse": {"sql"}, "fastapi": {"python", "rest-api", "http", "asyncio"},
           "django": {"python"}, "flask": {"python", "http"}, "aiohttp": {"python", "asyncio", "http"},
           "rest-api": {"http"}, "grpc": {"rest-api"}, "spring": {"java"}, "react": {"javascript", "typescript"},
           "vue": {"javascript", "typescript"}, "nextjs": {"react", "javascript", "typescript"}}


def _rub(v: int) -> str:
    return f"{v:,}".replace(",", "\u00a0") + "\u00a0₽"


def prize_text(lo: int, hi: int, basis: str) -> str:
    return (f"Прямой оффер в компанию с подтверждённой вилкой из потребности ({_rub(lo)} – {_rub(hi)} "
            f"{basis_title(basis)}) для топ-{TOP_N} призёров + очки в рейтинг ФСП")


def _tags(items: list[dict] | None) -> list[str]:
    return [i["tag"] for i in sorted(items or [], key=lambda i: -float(i.get("weight") or 0)) if i.get("tag")]


def _expand(tags: list[str]) -> set[str]:
    out = set(tags)
    for t in tags:
        out |= RELATED.get(t, set())
    return out


def category_for(need: EmployerNeed) -> tuple[str, str]:
    """Категория кубка по потребности: направление и грейд; Lead и Principal соревнуются в категории Senior."""
    req = need.requirements or {}
    d = need.direction_id or req.get("direction")
    g = need.grade_id or req.get("grade") or "middle"
    if d not in BASE_DIRECTIONS:
        raise api_error(422, "cup_need_direction",
                        "Турнир ФСП запускается для направлений Backend, Frontend, Data/ML, QA и ИБ — уточните потребность")
    return d, g if g in CUP_GRADES else "senior"


def pick_tasks(direction: str, need_grade: str, required: list[str], desired: list[str]) -> list[dict]:
    """Три семейства банка под обязательный стек (детерминированно), с объяснением совпадений."""
    from assessment_bank import load_specs

    from app.modules.assessment.skill_map import allowed_for_stack, to_stack_tags

    req, des = _expand(required), _expand(desired)
    stack = sorted(req | des)
    scored = []
    for s in load_specs().values():
        if s.direction not in (direction, "common") or s.format not in auto.AUTO_FORMATS or s.canary:
            continue
        if not allowed_for_stack(s.direction, s.skills, stack):
            continue
        tags = to_stack_tags(s.direction, s.skills)
        hit_req = [t for t in tags if t in req]
        hit_des = [t for t in tags if t in des and t not in req]
        fit = need_grade in s.target_grades
        score = 3 * len(hit_req) + len(hit_des) + (1.5 if fit else 0) + (0.5 if s.direction == direction else 0)
        scored.append((score, s, tags, hit_req, hit_des, fit))
    scored.sort(key=lambda x: (-x[0], x[1].family_id))
    chosen: list[tuple] = []
    for row in scored:  # сначала разные форматы, затем — лучшие по совпадению
        if len(chosen) < TASKS_N and row[1].format not in {c[1].format for c in chosen} and row[0] > 0:
            chosen.append(row)
    for row in scored:
        if len(chosen) >= TASKS_N:
            break
        if row not in chosen:
            chosen.append(row)
    if len(chosen) < TASKS_N:
        raise api_error(422, "cup_bank_too_small", "В банке мало заданий с автопроверкой под этот стек")
    return [{"family_id": s.family_id, "title": s.title, "format": s.format,
             "format_title": FORMAT_TITLES.get(s.format, s.format),
             "skills": [tag_title(t) for t in tags][:5], "matched": [tag_title(t) for t in hit_req + hit_des],
             "grade_fit": fit, "time_limit_s": s.time_limit_s}
            for _score, s, tags, hit_req, hit_des, fit in chosen]


def _salary(db: Session, need: EmployerNeed, cat: Category) -> tuple[int, int, str, str]:
    """Вилка приза: из потребности (с основанием) или — если в потребности её нет — рынок категории на руки."""
    req = need.requirements or {}
    lo = need.salary_from or req.get("salary_from")
    hi = need.salary_to or req.get("salary_to")
    basis = "net" if req.get("salary_net") else "gross"
    if lo or hi:
        lo, hi = int(lo or hi), int(hi or lo)
        if lo > hi or hi > inv_svc.SALARY_MAX_RATIO * lo:
            raise api_error(422, "cup_need_salary", "Вилка потребности шире правила платформы: «до» — не больше чем "
                                                    "в 1,5 раза выше «от». Уточните вилку в потребности")
        return lo, hi, basis, "need"
    lo, hi = int(cat.market_salary_from), int(cat.market_salary_to)
    if hi > inv_svc.SALARY_MAX_RATIO * lo:
        hi = int(lo * inv_svc.SALARY_MAX_RATIO) // 1000 * 1000
    return lo, hi, "net", "market"


def of(cup: Cup) -> dict | None:
    t = (cup.summary or {}).get("tournament")
    return t if isinstance(t, dict) and t.get("kind") == KIND else None


def public(cup: Cup, side: str) -> dict | None:
    """Паспорт турнира для ответа API: кандидату — без внутреннего номера потребности работодателя."""
    t = of(cup)
    if t is None or side == "employer":
        return t
    return {k: v for k, v in t.items() if k != "need_id"}


def existing(db: Session, company: Company, need_id) -> Cup | None:
    rows = db.scalars(select(Cup).where(Cup.company_id == company.id, Cup.status == "active")
                      .order_by(Cup.created_at.desc())).all()
    return next((c for c in rows if (of(c) or {}).get("need_id") == str(need_id)), None)


def create_from_need(db: Session, user: User, company: Company, need: EmployerNeed) -> tuple[Cup, bool]:
    """Турнир по потребности. Возвращает (кубок, создан ли сейчас)."""
    have = existing(db, company, need.id)
    if have is not None:
        return have, False
    req = need.requirements or {}
    direction, grade = category_for(need)
    cat = db.get(Category, f"{direction}.{grade}")
    if cat is None:
        raise api_error(422, "cup_need_category", "Для этой потребности нет категории кубка")
    required, desired = _tags(req.get("stack_required")), _tags(req.get("stack_desired"))
    picked = pick_tasks(direction, need.grade_id or req.get("grade") or grade, required, desired)
    lo, hi, basis, source = _salary(db, need, cat)
    stack_titles = [tag_title(t) for t in required] or [tag_title(t) for t in desired]
    prize = prize_text(lo, hi, basis)
    title = f"Кубок компании × ФСП: {need.title}"[:200]  # компания видна рядом (в карточке кубка, кабинете ФСП)
    stack_line = ", ".join(stack_titles) if stack_titles else category_title(cat.id)
    description = (f"Отборочный турнир ФСП под вакансию «{need.title}». Дисциплина — «{DISCIPLINE}». "
                   f"Три задания банка платформы с автопроверкой под стек: {stack_line}. У каждого участника свой "
                   f"вариант, {TIME_LIMIT_MIN} минут на решение, таблица — под псевдонимами.")  # приз — отдельно (паспорт)
    offer = (f"Прямой оффер по итогам отборочного турнира ФСП «{title}»: позиция «{need.title}» в компании "
             f"{company.name}. Вилка {_rub(lo)} – {_rub(hi)} {basis_title(basis)} — "
             f"{'из потребности работодателя' if source == 'need' else 'по рынку категории (в потребности не указана)'}. "
             f"Стек: {stack_line}.")
    data = {"title": title[:200], "description": description[:5000], "category_id": cat.id, "mode": "auto",
            "n_tasks": TASKS_N, "time_limit_min": TIME_LIMIT_MIN, "duration_days": DURATION_DAYS,
            "salary_from": lo, "salary_to": hi, "salary_basis": basis, "invite_top_n": TOP_N, "min_score": 0.5,
            "position_title": need.title[:200], "offer_description": offer[:5000],
            "contact_method": "Через платформу: контакты откроются после принятия приглашения"}
    cup = svc.create_cup(db, user, company, data)
    cup.task_families = [p["family_id"] for p in picked]
    cup.summary = {"tournament": {
        "kind": KIND, "need_id": str(need.id), "need_title": need.title, "discipline": DISCIPLINE,
        "title": "Кубок компании × ФСП", "prize": prize, "top_n": TOP_N, "rating_points": True,
        "stack": stack_titles, "stack_desired": [tag_title(t) for t in desired][:6],
        "category_id": cat.id, "category_title": category_title(cat.id), "need_grade": need.grade_id or req.get("grade"),
        "salary": {"from": lo, "to": hi, "basis": basis, "basis_title": basis_title(basis), "source": source},
        "tasks": picked, "bank_size": _bank_size(), "created_at": utcnow().isoformat()}}
    flag_modified(cup, "summary")
    db.commit()
    if company.is_demo:
        seed_statists(db, cup)
    return db.get(Cup, cup.id), True


def _bank_size() -> int:
    from assessment_bank import load_specs

    return len(load_specs())


def seed_statists(db: Session, cup: Cup, n: int = 6) -> int:
    """Демо-компания: «статисты» с результатами автопроверки (без тех, кого компания уже приглашала за 30 дней)."""
    from app.cup import demo

    rnd = random.Random(str(cup.id))
    since = utcnow() - timedelta(days=inv_svc.INVITATION_COOLDOWN_DAYS)
    invited = set(db.scalars(select(Invitation.candidate_user_id).where(
        Invitation.company_id == cup.company_id, Invitation.created_at >= since)).all())
    ps = demo._cands(db, cup.category_id, n, rnd, exclude=invited)
    now = utcnow()
    for i, (p, k) in enumerate(zip(ps, [3, 3, 2, 2, 1, 1]), start=1):
        spent = int(rnd.uniform(0.4, 0.9) * cup.time_limit_min * 60)
        e = demo._play(db, cup, p, rnd, i, state="scored", correct_n=k, spent_s=spent)
        e.started_at = now - timedelta(hours=rnd.uniform(2, 20))
        e.submitted_at = e.started_at + timedelta(seconds=e.time_spent_s or 600)
        e.deadline_at = e.started_at + timedelta(minutes=cup.time_limit_min)
    db.commit()
    return len(ps)


def invite_entry(db: Session, user: User, company: Company, cup: Cup, e: CupEntry) -> Invitation:
    """«Пригласить призёра турнира в 1 клик»: приглашение с вилкой кубка участнику из топ-N текущей таблицы."""
    if cup.status == "cancelled":
        raise api_error(409, "cup_cancelled", "Кубок отменён")
    if e.invitation_id:
        raise api_error(409, "cup_entry_invited", "Этот участник уже приглашён")
    if e.status != "scored" or e.score is None:
        raise api_error(409, "cup_entry_not_scored", "Пригласить можно участника с оценённым решением")
    rows = [x for x in svc.entries(db, cup.id) if x.status == "scored"]
    order = svc.ranked(rows)
    pos = next((i for i, x in enumerate(order, start=1) if x.id == e.id), None)
    if pos is None or pos > cup.invite_top_n:
        raise api_error(409, "cup_entry_not_prize", f"Пригласить в один клик можно призёров — топ-{cup.invite_top_n} таблицы")
    from app.modules.profiles.models import CandidateProfile

    prof = db.get(CandidateProfile, e.candidate_user_id)
    if prof is None or not prof.visible_to_employers:
        raise api_error(409, "cup_entry_hidden", "Участник скрыл профиль — приглашение недоступно")
    t = of(cup) or {}
    kind = "отборочного турнира ФСП" if t else "Кубка работодателя"
    total = len(order)
    text = (f"{cup.offer_description}\n\nПо итогам {kind} «{cup.title}»: {pos} место из {total}"
            f"{' (турнир идёт)' if cup.status != 'finished' else ''}, балл {round(e.score * 100)} %.")
    need = db.get(EmployerNeed, uuid.UUID(t["need_id"])) if t.get("need_id") else None
    inv = inv_svc.create_invitation(db, user, company, prof, position_title=cup.position_title,
                                    offer_description=text[:5000], salary_from=cup.salary_from,
                                    salary_to=cup.salary_to, contact_method=cup.contact_method,
                                    need_id=need.id if need is not None and need.company_id == company.id else None,
                                    probe_id=None, salary_basis=cup.salary_basis or "gross")
    inv.evidence = [{"level": "T1", "kind": "cup",
                     "text": f"{'Отборочный турнир ФСП' if t else 'Кубок работодателя'} «{cup.title}»: {pos} место из "
                             f"{total}, балл {round(e.score * 100)} %"}, *(inv.evidence or [])]
    flag_modified(inv, "evidence")
    e = db.get(CupEntry, e.id)
    e.invitation_id = inv.id
    e.invite_note = None
    db.commit()
    return inv


def cabinet_list(db: Session, scope_key: str | None) -> list[dict]:
    """Кабинет ФСП: турниры «Компания × ФСП» — платформы и своей песочницы жюри (агрегаты, без ПДн)."""
    from app.fsp_cabinet.analytics import kc

    rows = db.scalars(select(Cup).where(Cup.status != "cancelled").order_by(Cup.created_at.desc()).limit(200)).all()
    out = []
    for cup in rows:
        t = of(cup)
        if t is None or (cup.jury_scope is not None and cup.jury_scope != scope_key):
            continue
        es = svc.entries(db, cup.id)
        scored = [e for e in es if e.status == "scored"]
        comp = db.get(Company, cup.company_id)
        out.append({"id": str(cup.id), "title": cup.title, "company": comp.name if comp else None,
                    "discipline": t.get("discipline"), "position_title": cup.position_title,
                    "category_title": t.get("category_title"), "stack": t.get("stack") or [],
                    "tasks": [x.get("title") for x in t.get("tasks") or []], "prize": t.get("prize"),
                    "phase": svc.phase(cup), "ends_at": cup.ends_at.isoformat() if cup.ends_at else None,
                    "participants": kc(len(es)), "scored": kc(len(scored)),
                    "invited": kc(sum(1 for e in es if e.invitation_id)),
                    "best_pct": round(max(e.score for e in scored) * 100) if len(scored) >= 5 else None,
                    "is_demo": cup.is_demo})
    return out
