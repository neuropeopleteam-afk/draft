"""Вакансии и отклики (инициатива кандидата, ТЗ): работодатель публикует вакансию с обязательной вилкой,
кандидат видит список, откликается сам; статусы отклика видят обе стороны; контакты кандидата работодатель видит
только после отклика (отклик = согласие раскрыть контакты этой компании)."""
from __future__ import annotations

from typing import Literal
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.core.db import get_db, utcnow
from app.core.deps import get_current_user, require_role
from app.core.enums import UserRole
from app.core.errors import api_error, err
from app.integrations.egrul import trust
from app.integrations.push.service import notify_user
from app.integrations.vacancies import ats_import
from app.integrations.vacancies.models import Vacancy, VacancyApplication
from app.modules.assignments import service as assignments  # задание к вакансии (И7)
from app.modules.auth.models import User
from app.modules.catalog.models import Category
from app.modules.catalog.seed_data import STACK, category_title, known_tag
from app.modules.contact.salary import basis_out
from app.modules.contact.service import application_thread_summary
from app.modules.invitations.service import candidate_contacts, check_salary
from app.modules.jury import scope as jury_scope
from app.modules.matching.router import my_company
from app.modules.profiles.candidate_router import candidate_card_for
from app.modules.profiles.models import CandidateProfile, Company

employer_router = APIRouter(prefix="/api/employer", tags=["vacancies"])
public_router = APIRouter(prefix="/api", tags=["vacancies"])
candidate_router = APIRouter(prefix="/api/candidate", tags=["vacancies"])
employer = require_role(UserRole.employer)
candidate = require_role(UserRole.candidate)
E_AUTH = {401: err("Не выполнен вход"), 403: err("Только для работодателя"), 409: err("Нет профиля компании")}
C_AUTH = {401: err("Не выполнен вход"), 403: err("Только для кандидата")}
STATUS_TITLES = {"sent": "Отправлен", "viewed": "Просмотрен", "accepted": "Приглашение на интервью",
                 "rejected": "Отказ", "withdrawn": "Отозван кандидатом"}
FORMATS = "^(office|hybrid|remote|any)$"


class VacancyIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    category_id: str | None = Field(None, max_length=48)
    description: str = Field(min_length=20, max_length=5000)
    stack: list[str] = Field(default_factory=list, max_length=20)
    salary_from: int = Field(gt=0, le=10_000_000, description="Вилка обязательна")
    salary_to: int = Field(gt=0, le=10_000_000)
    salary_basis: Literal["gross", "net"] = Field("gross", description="gross — до вычета НДФЛ, net — на руки")
    work_format: str = Field("any", pattern=FORMATS)
    city: str | None = Field(None, max_length=100)
    publish: bool = True

    @model_validator(mode="after")
    def _range(self):
        if self.salary_from > self.salary_to:
            raise ValueError("Нижняя граница вилки больше верхней")
        return self


class VacancyPatch(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=200)
    category_id: str | None = Field(None, max_length=48)
    description: str | None = Field(None, min_length=20, max_length=5000)
    stack: list[str] | None = Field(None, max_length=20)
    salary_from: int | None = Field(None, gt=0, le=10_000_000)
    salary_to: int | None = Field(None, gt=0, le=10_000_000)
    salary_basis: Literal["gross", "net"] | None = None
    work_format: str | None = Field(None, pattern=FORMATS)
    city: str | None = Field(None, max_length=100)


def _event(kind: str, by: str, note: str | None = None) -> dict:
    return {"at": utcnow().isoformat(), "status": kind, "title": STATUS_TITLES.get(kind, kind), "by": by,
            **({"note": note} if note else {})}


def _vac_out(db: Session, v: Vacancy, *, company: Company | None = None, with_trust: bool = False,
             counts: dict | None = None, applied: VacancyApplication | None = None) -> dict:
    c = company or db.get(Company, v.company_id)
    out = {"id": str(v.id), "title": v.title, "category_id": v.category_id,
           "category_title": category_title(v.category_id) if v.category_id else None,
           "description": v.description, "stack": [{"tag": t, "title": STACK.get(t, (t,))[0]} for t in v.stack or []],
           "salary_from": v.salary_from, "salary_to": v.salary_to, "work_format": v.work_format, "city": v.city,
           "status": v.status, "published_at": v.published_at.isoformat() if v.published_at else None,
           "updated_at": v.updated_at.isoformat(), "is_demo": v.is_demo, **basis_out(v.salary_basis),
           # И23: импорт из ATS — бейдж «из «Потока»», ссылка, правилась ли после импорта
           "source": v.source, "source_title": ats_import.SOURCE_TITLE if v.source == ats_import.SOURCE else None,
           "external_id": v.external_id, "external_url": v.external_url,
           "imported_at": v.imported_at.isoformat() if v.imported_at else None,
           "edited_after_import": ats_import.edited_after_import(v) if v.source else None,
           "company": {"id": str(c.id), "name": c.name, "city": c.city, "industry": c.industry}}
    cat = db.get(Category, v.category_id) if v.category_id else None
    out["market_range"] = {"from": cat.market_salary_from, "to": cat.market_salary_to,
                           "median": cat.market_salary_median} if cat else None
    if with_trust:
        out["trust"] = trust.short(trust.compute(db, c, vacancy=v))
    if counts is not None:
        out["applications"] = counts
    if applied is not None:
        out["my_application"] = {"id": str(applied.id), "status": applied.status,
                                 "status_title": STATUS_TITLES[applied.status]}
    out["assignment"] = assignments.vacancy_brief(db, v.id)  # И7: откликнувшийся проходит задание работодателя
    return out


def _own_vacancy(db: Session, company: Company, vid: uuid.UUID) -> Vacancy:
    v = db.get(Vacancy, vid)
    if v is None or v.company_id != company.id:
        raise api_error(404, "vacancy_not_found", "Вакансия не найдена")
    return v


# Песочницы жюри: вакансия компании песочницы видна только её кандидатам — та же видимость, что у кандидатов в
# подборках (jury_scope.pool_clause), только по почте создателя компании. Компания без создателя — платформенная.
_Creator = aliased(User)


def _pool_join(stmt):
    return (stmt.join(Company, Company.id == Vacancy.company_id)
            .outerjoin(_Creator, _Creator.id == Company.created_by)
            .where(or_(_Creator.email.is_(None), jury_scope.pool_clause(_Creator.email))))


def _in_pool(db: Session, v: Vacancy) -> bool:
    """То же условие для одной вакансии (карточка, отклик)."""
    c = db.get(Company, v.company_id)
    creator = db.get(User, c.created_by) if c and c.created_by else None
    return creator is None or jury_scope.visible(creator.email)


def _check_refs(db: Session, category_id: str | None, stack: list[str] | None) -> None:
    if category_id and db.get(Category, category_id) is None:
        raise api_error(422, "category_unknown", "Неизвестная категория")
    bad = [t for t in stack or [] if not known_tag(t)]
    if bad:
        raise api_error(422, "stack_unknown", f"Неизвестные технологии: {', '.join(bad[:5])}")


# ------------------------------------------------------------------ работодатель

@employer_router.get("/vacancies", summary="Вакансии моей компании со счётчиками откликов", responses=E_AUTH)
def my_vacancies(user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    c = my_company(db, user)
    rows = db.scalars(select(Vacancy).where(Vacancy.company_id == c.id).order_by(Vacancy.updated_at.desc())).all()
    cnt: dict = {}
    for vid, st, n in db.execute(select(VacancyApplication.vacancy_id, VacancyApplication.status, func.count())
                                 .join(Vacancy, Vacancy.id == VacancyApplication.vacancy_id)
                                 .where(Vacancy.company_id == c.id)
                                 .group_by(VacancyApplication.vacancy_id, VacancyApplication.status)):
        cnt.setdefault(vid, {"total": 0, "new": 0})
        if st != "withdrawn":
            cnt[vid]["total"] += n
        if st == "sent":
            cnt[vid]["new"] += n
    return [_vac_out(db, v, company=c, counts=cnt.get(v.id, {"total": 0, "new": 0})) for v in rows]


# ------------------------------------------------------------------ импорт из ATS (И23)
class ImportIn(BaseModel):
    job_ids: list[int] | None = Field(None, max_length=200, description="id вакансий в «Потоке»; пусто — все")
    publish: bool = Field(True, description="Публиковать сразу, если в «Потоке» указана вилка в рублях и открыта вакансия")


def _import_error(e: ats_import.AtsError):
    if e.status == 422:
        return api_error(422, "potok_not_connected", "«Поток» не подключён: укажите токен компании в разделе "
                         "«Интеграция с ATS» (или включите демо-режим «Потока») и повторите импорт")
    return api_error(502, "potok_error", str(e))


@employer_router.get("/vacancies/import/potok/preview", summary="Импорт из «Потока»: вакансии ATS и что с ними будет",
                     responses={**E_AUTH, 422: err("«Поток» не подключён (нет токена)"), 502: err("«Поток» ответил ошибкой")})
def import_preview(user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    try:
        return ats_import.preview(db, c.id)
    except ats_import.AtsError as e:
        raise _import_error(e) from None


@employer_router.post("/vacancies/import/potok", summary="Импортировать вакансии из «Потока» (только чтение /jobs)",
                      responses={**E_AUTH, 422: err("«Поток» не подключён (нет токена)"), 502: err("«Поток» ответил ошибкой")})
def import_from_potok(data: ImportIn, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    try:
        return ats_import.run_import(db, c, user, data.job_ids, publish=data.publish)
    except ats_import.AtsError as e:
        db.rollback()
        raise _import_error(e) from None


@employer_router.post("/vacancies", status_code=201, summary="Создать вакансию (вилка «от–до» обязательна)",
                      responses={**E_AUTH, 422: err("Нет вилки или неизвестная категория/технология")})
def create_vacancy(data: VacancyIn, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    _check_refs(db, data.category_id, data.stack)
    check_salary(data.salary_from, data.salary_to)  # ширина ≤ 1,5 — как у приглашений, зондов и кубков
    v = Vacancy(company_id=c.id, created_by=user.id, title=data.title.strip(), category_id=data.category_id,
                description=data.description.strip(), stack=list(dict.fromkeys(data.stack)),
                salary_from=data.salary_from, salary_to=data.salary_to, salary_basis=data.salary_basis,
                work_format=data.work_format,
                city=data.city, status="published" if data.publish else "draft",
                published_at=utcnow() if data.publish else None, is_demo=user.is_demo)
    db.add(v)
    db.commit()
    return _vac_out(db, v, company=c, counts={"total": 0, "new": 0})


@employer_router.patch("/vacancies/{vid}", summary="Изменить вакансию", responses={**E_AUTH, 404: err("Не найдена")})
def patch_vacancy(vid: uuid.UUID, data: VacancyPatch, user: User = Depends(employer),
                  db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    v = _own_vacancy(db, c, vid)
    upd = data.model_dump(exclude_unset=True)
    if "salary_from" in upd and upd["salary_from"] is None or "salary_to" in upd and upd["salary_to"] is None:
        raise api_error(422, "salary_required", "Вилка «от–до» обязательна")
    _check_refs(db, upd.get("category_id"), upd.get("stack"))
    lo, hi = upd.get("salary_from", v.salary_from), upd.get("salary_to", v.salary_to)
    if lo > hi:
        raise api_error(422, "salary_range", "Нижняя граница вилки больше верхней")
    if "salary_from" in upd or "salary_to" in upd:  # старые демо-вакансии с широкой вилкой правятся без ошибки
        check_salary(lo, hi)
    if upd.get("salary_basis", "") is None:
        upd.pop("salary_basis")
    for k, val in upd.items():
        setattr(v, k, val)
    db.commit()
    return _vac_out(db, v, company=c)


def _set_status(db: Session, user: User, vid: uuid.UUID, status: str) -> dict:
    c = my_company(db, user)
    v = _own_vacancy(db, c, vid)
    v.status = status
    if status == "published":
        v.published_at = utcnow()
    db.commit()
    return _vac_out(db, v, company=c)


@employer_router.post("/vacancies/{vid}/publish", summary="Опубликовать", responses={**E_AUTH, 404: err("Не найдена")})
def publish(vid: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    return _set_status(db, user, vid, "published")


@employer_router.post("/vacancies/{vid}/close", summary="Снять с публикации", responses={**E_AUTH, 404: err("Не найдена")})
def close(vid: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)) -> dict:
    return _set_status(db, user, vid, "closed")


def _app_out(db: Session, a: VacancyApplication, side: str, v: Vacancy | None = None) -> dict:
    v = v or db.get(Vacancy, a.vacancy_id)
    out = {"id": str(a.id), "vacancy_id": str(a.vacancy_id), "vacancy_title": v.title, "status": a.status,
           "status_title": STATUS_TITLES[a.status], "events": a.events, "cover_letter": a.cover_letter,
           "created_at": a.created_at.isoformat(), "viewed_at": a.viewed_at.isoformat() if a.viewed_at else None,
           "responded_at": a.responded_at.isoformat() if a.responded_at else None,
           "salary_from": v.salary_from, "salary_to": v.salary_to, **basis_out(v.salary_basis),
           "thread": application_thread_summary(db, a.id, side)}  # переписка по отклику (app.modules.contact)
    from app.integrations.ats.stages import stage_out

    out["ats_stage"] = stage_out(a.ats_stage, side)  # обратный канал: этап у работодателя по данным его ATS
    if side == "employer":
        out["employer_note"] = a.employer_note
        out["card"] = candidate_card_for(db, a.candidate_user_id, include_hidden=False)
        out["contacts"] = candidate_contacts(db, a.candidate_user_id) if a.status != "withdrawn" else None
    else:
        c = db.get(Company, v.company_id)
        out["company"] = {"id": str(c.id), "name": c.name}
        out["employer_note"] = a.employer_note if a.status in ("accepted", "rejected") else None
    out["assignment"] = assignments.attempt_for_application(db, a, side)  # И7: результат задания рядом с откликом
    return out


@employer_router.get("/vacancies/{vid}/applications", summary="Отклики на вакансию: карточка и контакты кандидата",
                     responses={**E_AUTH, 404: err("Не найдена")})
def vacancy_applications(vid: uuid.UUID, user: User = Depends(employer), db: Session = Depends(get_db)) -> list[dict]:
    c = my_company(db, user)
    v = _own_vacancy(db, c, vid)
    rows = db.scalars(select(VacancyApplication).where(VacancyApplication.vacancy_id == v.id)
                      .order_by(VacancyApplication.created_at.desc())).all()
    return [_app_out(db, a, "employer", v) for a in rows]


def _own_application(db: Session, c: Company, app_id: uuid.UUID) -> tuple[VacancyApplication, Vacancy]:
    a = db.get(VacancyApplication, app_id)
    v = db.get(Vacancy, a.vacancy_id) if a else None
    if a is None or v is None or v.company_id != c.id:
        raise api_error(404, "application_not_found", "Отклик не найден")
    return a, v


@employer_router.post("/applications/{app_id}/view", summary="Отметить отклик просмотренным",
                      responses={**E_AUTH, 404: err("Отклик не найден")})
def view_application(app_id: uuid.UUID, bg: BackgroundTasks, user: User = Depends(employer),
                     db: Session = Depends(get_db)) -> dict:
    a, v = _own_application(db, my_company(db, user), app_id)
    if a.status == "sent":
        a.status, a.viewed_at = "viewed", utcnow()
        a.events = [*a.events, _event("viewed", "employer")]
        db.commit()
        bg.add_task(notify_user, a.candidate_user_id, "Отклик просмотрен", f"«{v.title}»: работодатель открыл отклик",
                    "/candidate/vacancies", f"app-{a.id}")
    return _app_out(db, a, "employer", v)


class DecisionIn(BaseModel):
    status: str = Field(pattern="^(accepted|rejected)$")
    note: str | None = Field(None, max_length=1000, description="Сообщение кандидату: следующий шаг или причина отказа")


@employer_router.post("/applications/{app_id}/status", summary="Ответить на отклик: пригласить на интервью или отказать",
                      responses={**E_AUTH, 404: err("Отклик не найден"), 409: err("Отклик отозван")})
def decide(app_id: uuid.UUID, data: DecisionIn, bg: BackgroundTasks, user: User = Depends(employer),
           db: Session = Depends(get_db)) -> dict:
    c = my_company(db, user)
    a, v = _own_application(db, c, app_id)
    if a.status == "withdrawn":
        raise api_error(409, "application_withdrawn", "Кандидат отозвал отклик")
    a.status, a.responded_at, a.employer_note = data.status, utcnow(), data.note
    a.viewed_at = a.viewed_at or utcnow()
    a.events = [*a.events, _event(data.status, "employer", data.note)]
    db.commit()
    title = "Вас приглашают на интервью" if data.status == "accepted" else "Ответ по отклику"
    bg.add_task(notify_user, a.candidate_user_id, title, f"{c.name}: «{v.title}» — {STATUS_TITLES[data.status]}",
                "/candidate/vacancies", f"app-{a.id}")
    if data.status == "accepted":
        from app.integrations.ats.providers import enabled_targets
        from app.integrations.ats.service import company_settings

        st = company_settings(db, c.id)  # строки настроек может не быть — по умолчанию auto_push=True
        db.commit()
        if st.auto_push and enabled_targets(db, c.id, st):
            from app.integrations.ats.service import deliver_bg

            bg.add_task(deliver_bg, c.id, application_id=a.id, trigger="application_accepted")
    return _app_out(db, a, "employer", v)


# ------------------------------------------------------------------ кандидат и публичный список

@public_router.get("/vacancies", summary="Опубликованные вакансии с индексом доверия работодателя")
def list_vacancies(q: str | None = Query(None, max_length=100), direction: str | None = Query(None, max_length=32),
                   category_id: str | None = Query(None, max_length=48), salary_min: int | None = Query(None, ge=0),
                   work_format: str | None = Query(None, pattern=FORMATS), limit: int = Query(50, ge=1, le=100),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    stmt = _pool_join(select(Vacancy).where(Vacancy.status == "published"))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Vacancy.title.ilike(like), Vacancy.description.ilike(like), Company.name.ilike(like)))
    if category_id:
        stmt = stmt.where(Vacancy.category_id == category_id)
    elif direction:
        stmt = stmt.where(Vacancy.category_id.like(f"{direction}.%"))
    if salary_min:
        stmt = stmt.where(Vacancy.salary_to >= salary_min)
    if work_format and work_format != "any":
        stmt = stmt.where(Vacancy.work_format.in_([work_format, "any"]))
    rows = db.scalars(stmt.order_by(Vacancy.published_at.desc().nullslast()).limit(limit)).all()
    mine = {}
    if user.role == UserRole.candidate and rows:
        mine = {a.vacancy_id: a for a in db.scalars(select(VacancyApplication).where(
            VacancyApplication.candidate_user_id == user.id,
            VacancyApplication.vacancy_id.in_([v.id for v in rows]))).all()}
    cp = db.get(CandidateProfile, user.id) if user.role == UserRole.candidate else None
    return {"items": [_vac_out(db, v, with_trust=True, applied=mine.get(v.id)) for v in rows],
            "my_category_id": cp.current_category_id if cp else None}


@public_router.get("/vacancies/{vid}", summary="Вакансия: описание, вилка, рынок, индекс доверия работодателя",
                   responses={404: err("Вакансия не найдена")})
def get_vacancy(vid: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    v = db.get(Vacancy, vid)
    own = user.role == UserRole.employer and v is not None and _is_own(db, user, v)
    if v is None or (v.status != "published" and not own) or (not own and not _in_pool(db, v)):
        raise api_error(404, "vacancy_not_found", "Вакансия не найдена")
    mine = db.scalar(select(VacancyApplication).where(VacancyApplication.vacancy_id == v.id,
                                                      VacancyApplication.candidate_user_id == user.id))
    out = _vac_out(db, v, applied=mine)
    out["trust"] = trust.compute(db, db.get(Company, v.company_id), vacancy=v)
    return out


def _is_own(db: Session, user: User, v: Vacancy) -> bool:
    try:
        return my_company(db, user).id == v.company_id
    except Exception:  # noqa: BLE001 — нет компании
        return False


class ApplyIn(BaseModel):
    cover_letter: str | None = Field(None, max_length=3000)
    consent_contacts: bool = Field(description="Согласие раскрыть контакты этой компании")


@public_router.post("/vacancies/{vid}/apply", status_code=201, summary="Откликнуться на вакансию (контакты откроются компании)",
                    responses={**C_AUTH, 404: err("Вакансия не найдена"), 409: err("Уже есть отклик"),
                               422: err("Нужно согласие раскрыть контакты")})
def apply(vid: uuid.UUID, data: ApplyIn, bg: BackgroundTasks, user: User = Depends(candidate),
          db: Session = Depends(get_db)) -> dict:
    v = db.get(Vacancy, vid)
    if v is None or v.status != "published" or not _in_pool(db, v):
        raise api_error(404, "vacancy_not_found", "Вакансия не найдена или снята с публикации")
    if not data.consent_contacts:
        raise api_error(422, "consent_required", "Отклик раскрывает ваши контакты компании — подтвердите согласие")
    a = db.scalar(select(VacancyApplication).where(VacancyApplication.vacancy_id == v.id,
                                                   VacancyApplication.candidate_user_id == user.id))
    if a is not None and a.status != "withdrawn":
        raise api_error(409, "already_applied", "Вы уже откликнулись на эту вакансию")
    if a is None:
        a = VacancyApplication(vacancy_id=v.id, candidate_user_id=user.id, events=[])
        db.add(a)
    a.status, a.cover_letter, a.viewed_at, a.responded_at, a.employer_note = "sent", data.cover_letter, None, None, None
    a.events = [*(a.events or []), _event("sent", "candidate")]
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise api_error(409, "already_applied", "Вы уже откликнулись на эту вакансию") from None
    if v.created_by:
        ref = db.get(CandidateProfile, user.id).public_ref
        bg.add_task(notify_user, v.created_by, f"Новый отклик: {ref}", f"«{v.title}»", "/employer/vacancies",
                    f"vac-{v.id}")
    if assignments.on_application(db, v, a) is not None:  # И7: к вакансии прикреплено задание — предложить его
        db.commit()
    return _app_out(db, a, "candidate", v)


@candidate_router.get("/applications", summary="Мои отклики со статусами и историей", responses=C_AUTH)
def my_applications(user: User = Depends(candidate), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(VacancyApplication).where(VacancyApplication.candidate_user_id == user.id)
                      .order_by(VacancyApplication.updated_at.desc())).all()
    return [_app_out(db, a, "candidate") for a in rows]


@candidate_router.post("/applications/{app_id}/withdraw", summary="Отозвать отклик",
                       responses={**C_AUTH, 404: err("Отклик не найден")})
def withdraw(app_id: uuid.UUID, user: User = Depends(candidate), db: Session = Depends(get_db)) -> dict:
    a = db.get(VacancyApplication, app_id)
    if a is None or a.candidate_user_id != user.id:
        raise api_error(404, "application_not_found", "Отклик не найден")
    if a.status != "withdrawn":
        a.status = "withdrawn"
        a.events = [*a.events, _event("withdrawn", "candidate")]
        db.commit()
    return _app_out(db, a, "candidate")
