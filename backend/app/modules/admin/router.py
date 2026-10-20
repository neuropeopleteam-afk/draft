"""Роутеры службы поддержки (/api/support), заявок на тарифы (/api/tariffs/request) и мини-админки (/api/admin)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
import logging
import os
from pathlib import Path
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Query, status
import jwt
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import as_aware, get_db, utcnow
from app.core.deps import get_current_user, oauth2_scheme, require_role
from app.core.enums import InvitationStatus, TestSessionStatus, UserRole
from app.core.errors import api_error, err
from app.core.flags import jury_on
from app.core.security import decode_access_token
from app.modules.admin.models import SupportTicket, TariffRequest
from app.modules.assessment.models import TestSession
from app.modules.auth.models import User
from app.modules.invitations.models import Invitation
from app.modules.matching.models import EmployerNeed
from app.modules.notifications.mailer import Message, get_mailer
from app.modules.profiles.models import CandidateProfile, Company, EmployerProfile
from app.modules.tariffs import plans as tariff_plans
from app.modules.tariffs import service as tariff_svc
from app.modules.tariffs.models import CompanyTariff, DemoInvoice

log = logging.getLogger("app.admin")
MSK = timezone(timedelta(hours=3))

admin_only = require_role(UserRole.admin)
employer_only = require_role(UserRole.employer)

ADMIN_ERR = {401: err("Не выполнен вход"), 403: err("Только для администратора")}
AUTH_ERR = {401: err("Не выполнен вход")}
EMP_ERR = {401: err("Не выполнен вход"), 403: err("Только для работодателя")}

TAGS = [
    {"name": "support", "description": "Служба поддержки и обратная связь (/support): приём обращений и история своих заявок"},
    {"name": "admin", "description": "Мини-админка (/admin): пользователи, компании, заявки на тарифы и партнёрство, обращения, флаги и воронка продукта"},
]

support_router = APIRouter(prefix="/api/support", tags=["support"])
tariff_request_router = APIRouter(prefix="/api/tariffs", tags=["tariffs"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


def get_optional_user(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User | None:
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        if payload.get("typ"):
            return None
        uid = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    u = db.get(User, uid)
    if u is None or not u.is_active or payload.get("ver", 0) != u.token_version:
        return None
    return u


# ------------------------------------------------------------------ Схемы запросов


class SupportTicketIn(BaseModel):
    email: EmailStr | None = Field(None, description="Контактная почта (для вошедшего пользователя подставляется автоматически)")
    name: str | None = Field(None, max_length=200)
    category: Literal["general", "tariff", "technical", "privacy", "partner"] = "general"
    subject: str = Field(min_length=3, max_length=200)
    message: str = Field(min_length=5, max_length=4000)


class TariffRequestIn(BaseModel):
    plan: Literal["hire", "partner"] = "hire"
    company_name: str | None = Field(None, max_length=200)
    contact_name: str | None = Field(None, max_length=200)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(None, max_length=64)
    comment: str | None = Field(None, max_length=1000)


class AdminUserStatusIn(BaseModel):
    user_id: uuid.UUID
    is_active: bool | None = None
    role: UserRole | None = None


class AdminCompanyTariffIn(BaseModel):
    company_id: uuid.UUID
    plan: Literal["start", "hire", "partner"]
    note: str | None = Field(None, max_length=300)


class AdminTariffResolveIn(BaseModel):
    request_id: uuid.UUID
    action: Literal["approve", "reject"]
    admin_note: str | None = Field(None, max_length=500)


class AdminSupportResolveIn(BaseModel):
    ticket_id: uuid.UUID
    status: Literal["resolved", "closed"] = "resolved"
    admin_reply: str | None = Field(None, max_length=2000)


class AdminFlagsIn(BaseModel):
    jury_mode: bool


# ------------------------------------------------------------------ Форматирование


def _ticket_out(t: SupportTicket) -> dict:
    return {
        "id": str(t.id),
        "user_id": str(t.user_id) if t.user_id else None,
        "role": t.role,
        "email": t.email,
        "name": t.name,
        "category": t.category,
        "subject": t.subject,
        "message": t.message,
        "status": t.status,
        "admin_reply": t.admin_reply,
        "resolved_at": as_aware(t.resolved_at).isoformat() if t.resolved_at else None,
        "created_at": as_aware(t.created_at).isoformat(),
    }


def _tariff_req_out(r: TariffRequest) -> dict:
    return {
        "id": str(r.id),
        "company_id": str(r.company_id) if r.company_id else None,
        "user_id": str(r.user_id) if r.user_id else None,
        "plan": r.plan,
        "plan_title": tariff_plans.plan(r.plan)["title"],
        "company_name": r.company_name,
        "contact_name": r.contact_name,
        "contact_email": r.contact_email,
        "contact_phone": r.contact_phone,
        "comment": r.comment,
        "status": r.status,
        "admin_note": r.admin_note,
        "resolved_at": as_aware(r.resolved_at).isoformat() if r.resolved_at else None,
        "created_at": as_aware(r.created_at).isoformat(),
    }


def _send_mail_safe(to: str, subject: str, text: str) -> None:
    if to.endswith((".invalid", "@jury.example.com")):
        return
    try:
        get_mailer().send(Message(to=to, subject=subject, text=text))
    except Exception:  # noqa: BLE001
        log.exception("Не удалось отправить письмо %r на %s", subject, to)


# ------------------------------------------------------------------ Служба поддержки (/api/support)


@support_router.get("", summary="Контакты службы поддержки и категории обращений (публично)")
def support_meta() -> dict:
    s = get_settings()
    return {
        "support_email": s.support_email,
        "legal_email": "<форма обратной связи>",
        "categories": [
            {"id": "general", "title": "Общий вопрос по платформе"},
            {"id": "tariff", "title": "Подключение тарифа «Найм» и договоры"},
            {"id": "partner", "title": "Партнёрство и спонсорские пакеты ФСП"},
            {"id": "technical", "title": "Техническая поддержка и доступ к аккаунту"},
            {"id": "privacy", "title": "Персональные данные (152-ФЗ)"},
        ],
    }


@support_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Отправить обращение в службу поддержки (запись в БД и уведомление на почту поддержки)",
    responses={422: err("Не указана контактная почта (`email_required`) или неверные поля")},
)
def create_support_ticket(
    data: SupportTicketIn,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    s = get_settings()
    email = (str(data.email).strip().lower() if data.email else None) or (user.email if user else None)
    if not email:
        raise api_error(422, "email_required", "Укажите контактную почту для ответа")
    name = (data.name or "").strip() or None
    if not name and user:
        cp = db.get(CandidateProfile, user.id)
        ep = db.get(EmployerProfile, user.id)
        name = (cp.full_name if cp else None) or (ep.full_name if ep else None)
    ticket = SupportTicket(
        user_id=user.id if user else None,
        role=user.role.value if user else None,
        email=email,
        name=name,
        category=data.category,
        subject=data.subject.strip(),
        message=data.message.strip(),
        status="open",
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    _send_mail_safe(
        s.support_email,
        f"[{s.product_name} · Поддержка] {ticket.subject}",
        f"Новое обращение #{ticket.id}\nОт: {name or '—'} <{email}>\nКатегория: {ticket.category}\n\n{ticket.message}",
    )
    return {
        "ticket": _ticket_out(ticket),
        "support_email": s.support_email,
        "message": "Обращение зарегистрировано. Ответ придёт на указанную почту и появится в разделе «Поддержка».",
    }


@support_router.get("/my", summary="Мои обращения в службу поддержки", responses=AUTH_ERR)
def my_support_tickets(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(
        select(SupportTicket)
        .where((SupportTicket.user_id == user.id) | (SupportTicket.email == user.email))
        .order_by(SupportTicket.created_at.desc())
        .limit(30)
    ).all()
    return {"items": [_ticket_out(r) for r in rows]}


# ------------------------------------------------------------------ Заявка на тариф (/api/tariffs/request)


@tariff_request_router.post(
    "/request",
    status_code=status.HTTP_201_CREATED,
    summary="Оставить заявку на подключение тарифа «Найм» или «Партнёр ФСП» (без автоподключения, включает админ)",
    responses={422: err("Не указаны название компании (`company_required`) или контактная почта (`email_required`)")},
)
def create_tariff_request(
    data: TariffRequestIn,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    s = get_settings()
    company: Company | None = None
    if user and user.role == UserRole.employer:
        ep = db.get(EmployerProfile, user.id)
        if ep and ep.company_id:
            company = db.get(Company, ep.company_id)

    company_name = (data.company_name or "").strip() or (company.name if company else "")
    if not company_name:
        raise api_error(422, "company_required", "Укажите название компании")

    contact_email = (str(data.contact_email).strip().lower() if data.contact_email else "") or (
        user.email if user else (company.contact_email or "" if company else "")
    )
    if not contact_email:
        raise api_error(422, "email_required", "Укажите контактную почту")

    contact_name = (data.contact_name or "").strip() or None
    if not contact_name and user:
        ep = db.get(EmployerProfile, user.id)
        contact_name = ep.full_name if ep else None

    req = TariffRequest(
        company_id=company.id if company else None,
        user_id=user.id if user else None,
        plan=data.plan,
        company_name=company_name,
        contact_name=contact_name,
        contact_email=contact_email,
        contact_phone=(data.contact_phone or "").strip() or None,
        comment=(data.comment or "").strip() or None,
        status="pending",
    )
    db.add(req)

    # Для заявки «Партнёр ФСП» от вошедшего работодателя отмечаем и в CompanyTariff, чтобы её видел кабинет ФСП
    if company is not None and data.plan == "partner":
        row = tariff_svc.ensure_row(db, company)
        if not row.fsp_partner:
            row.partner_requested_at = utcnow()
            row.partner_request_note = ((data.comment or "").strip()[:500] or "Заявка со страницы тарифов")

    db.commit()
    db.refresh(req)
    _send_mail_safe(
        s.support_email,
        f"[{s.product_name} · Заявка на тариф] {tariff_plans.plan(req.plan)['title']} — {req.company_name}",
        (
            f"Заявка на тариф «{tariff_plans.plan(req.plan)['title']}»\n"
            f"Компания: {req.company_name}\n"
            f"Контакт: {req.contact_name or '—'} <{req.contact_email}> {req.contact_phone or ''}\n"
            f"Комментарий: {req.comment or '—'}"
        ),
    )
    return {
        "request": _tariff_req_out(req),
        "message": (
            f"Заявка на тариф «{tariff_plans.plan(req.plan)['title']}» принята. "
            "Менеджер свяжется с вами для согласования условий и договора, после чего тариф будет активирован администратором."
        ),
    }


@tariff_request_router.get(
    "/requests/my",
    summary="Заявки моей компании на подключение тарифов",
    responses=EMP_ERR,
)
def my_tariff_requests(user: User = Depends(employer_only), db: Session = Depends(get_db)) -> dict:
    ep = db.get(EmployerProfile, user.id)
    cid = ep.company_id if ep else None
    rows = db.scalars(
        select(TariffRequest)
        .where((TariffRequest.user_id == user.id) | ((TariffRequest.company_id == cid) if cid else False))
        .order_by(TariffRequest.created_at.desc())
        .limit(20)
    ).all()
    return {"items": [_tariff_req_out(r) for r in rows]}


# ------------------------------------------------------------------ Мини-админка (/api/admin)


def _apply_company_tariff(db: Session, company: Company, plan_id: str, actor: User, note: str | None = None) -> CompanyTariff:
    row = tariff_svc.ensure_row(db, company)
    if plan_id == "partner":
        row.fsp_partner = True
        row.partner_since = utcnow()
        row.partner_granted_by = actor.id
        row.partner_note = (note or "").strip()[:300] or row.partner_note or "Подключено администратором"
        row.partner_requested_at = None
    else:
        row.fsp_partner = False
        row.partner_since = None
        row.partner_granted_by = None
        row.plan = plan_id
        row.plan_since = utcnow()
        row.changed_by = actor.id
        if plan_id == "hire":
            today = utcnow().astimezone(MSK).date()
            inv = DemoInvoice(
                company_id=company.id,
                number=f"Д-{utcnow().astimezone(MSK):%Y%m}-{uuid.uuid4().hex[:6].upper()}",
                plan="hire",
                amount_rub=None,
                vat_rub=None,
                period_from=today,
                period_to=today + timedelta(days=30),
                status="demo",
                created_by=actor.id,
            )
            db.add(inv)
    return row


def _compute_funnel(db: Session, include_demo: bool = False, days: int = 14) -> dict:
    user_cond = [] if include_demo else [User.is_demo.is_(False)]
    comp_cond = [] if include_demo else [Company.is_demo.is_(False)]

    users = db.scalars(select(User).where(*user_cond)).all()
    user_ids = {u.id for u in users}
    companies = db.scalars(select(Company).where(*comp_cond)).all()
    comp_ids = {c.id for c in companies}

    sessions = [
        s
        for s in db.scalars(select(TestSession)).all()
        if s.user_id in user_ids
    ]
    finished_sessions = [s for s in sessions if s.status == TestSessionStatus.finished]

    needs = [
        n
        for n in db.scalars(select(EmployerNeed)).all()
        if n.company_id in comp_ids
    ]
    invs = [
        i
        for i in db.scalars(select(Invitation)).all()
        if i.company_id in comp_ids
    ]
    accepted_invs = [i for i in invs if i.status == InvitationStatus.accepted]

    cand_profiles = [
        cp
        for cp in db.scalars(select(CandidateProfile)).all()
        if cp.user_id in user_ids and cp.current_category_id is not None
    ]

    today = utcnow().astimezone(MSK).date()
    by_day = []
    for offset in range(days - 1, -1, -1):
        d = today - timedelta(days=offset)
        d_str = d.isoformat()
        by_day.append(
            {
                "date": d_str,
                "registrations": sum(1 for u in users if as_aware(u.created_at).astimezone(MSK).date() == d),
                "tests_finished": sum(
                    1
                    for s in finished_sessions
                    if s.finished_at and as_aware(s.finished_at).astimezone(MSK).date() == d
                ),
                "needs_created": sum(1 for n in needs if as_aware(n.created_at).astimezone(MSK).date() == d),
                "invitations_sent": sum(1 for i in invs if as_aware(i.created_at).astimezone(MSK).date() == d),
                "invitations_accepted": sum(
                    1
                    for i in accepted_invs
                    if as_aware(i.responded_at or i.created_at).astimezone(MSK).date() == d
                ),
            }
        )

    return {
        "include_demo": include_demo,
        "days": days,
        "totals": {
            "registrations": len(users),
            "verified_users": sum(1 for u in users if u.is_email_verified),
            "candidates": sum(1 for u in users if u.role == UserRole.candidate),
            "employers": sum(1 for u in users if u.role == UserRole.employer),
            "tests_started": len(sessions),
            "tests_finished": len(finished_sessions),
            "confirmed_grades": len(cand_profiles),
            "needs_created": len(needs),
            "invitations_sent": len(invs),
            "invitations_accepted": len(accepted_invs),
        },
        "by_day": by_day,
    }


def _flags_state() -> dict:
    s = get_settings()
    return {
        "jury_mode": jury_on(),
        "jury_mode_env": bool(s.jury_mode_available),
        "tariffs_enabled": bool(s.tariffs_enabled),
        "demo_sandbox": bool(s.demo_sandbox),
        "study_enabled": bool(s.study_enabled),
        "support_email": s.support_email,
    }


@admin_router.get("/overview", summary="Сводка мини-админки: счётчики, заявки, флаги и воронка продукта", responses=ADMIN_ERR)
def admin_overview(
    include_demo: bool = Query(False, description="Включать демо-учётки и демо-компании в воронку"),
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    by_role = dict(
        db.execute(select(User.role, func.count(User.id)).where(User.is_demo.is_(False)).group_by(User.role)).all()
    )
    pending_tariffs = int(
        db.scalar(select(func.count(TariffRequest.id)).where(TariffRequest.status == "pending")) or 0
    )
    pending_partners = int(
        db.scalar(
            select(func.count(CompanyTariff.company_id)).where(
                CompanyTariff.fsp_partner.is_(False),
                CompanyTariff.partner_requested_at.is_not(None),
            )
        )
        or 0
    )
    open_tickets = int(
        db.scalar(select(func.count(SupportTicket.id)).where(SupportTicket.status == "open")) or 0
    )
    companies_real = int(db.scalar(select(func.count(Company.id)).where(Company.is_demo.is_(False))) or 0)
    return {
        "users_real": sum(int(v) for v in by_role.values()),
        "users_by_role": {str(k.value if hasattr(k, "value") else k): int(v) for k, v in by_role.items()},
        "companies_real": companies_real,
        "pending_tariff_requests": pending_tariffs,
        "pending_partner_requests": pending_partners,
        "open_support_tickets": open_tickets,
        "flags": _flags_state(),
        "funnel": _compute_funnel(db, include_demo=include_demo, days=14),
    }


@admin_router.get("/funnel", summary="Воронка продукта по дням на собственных данных платформы", responses=ADMIN_ERR)
def admin_funnel(
    include_demo: bool = Query(False),
    days: int = Query(14, ge=7, le=90),
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    return _compute_funnel(db, include_demo=include_demo, days=days)


@admin_router.get("/users", summary="Список пользователей платформы", responses=ADMIN_ERR)
def admin_users(
    include_demo: bool = Query(False),
    role: str | None = Query(None),
    q: str | None = Query(None, max_length=100),
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(User)
    if not include_demo:
        stmt = stmt.where(User.is_demo.is_(False))
    if role:
        stmt = stmt.where(User.role == role)
    if q and q.strip():
        stmt = stmt.where(User.email.ilike(f"%{q.strip()}%"))
    rows = db.scalars(stmt.order_by(User.created_at.desc()).limit(100)).all()
    items = []
    for u in rows:
        cp = db.get(CandidateProfile, u.id)
        ep = db.get(EmployerProfile, u.id)
        comp = db.get(Company, ep.company_id) if ep and ep.company_id else None
        items.append(
            {
                "id": str(u.id),
                "email": u.email,
                "role": u.role.value,
                "is_active": u.is_active,
                "is_email_verified": u.is_email_verified,
                "is_demo": u.is_demo,
                "full_name": (cp.full_name if cp else None) or (ep.full_name if ep else None),
                "company_name": comp.name if comp else None,
                "company_id": str(comp.id) if comp else None,
                "created_at": as_aware(u.created_at).isoformat(),
                "last_login_at": as_aware(u.last_login_at).isoformat() if u.last_login_at else None,
            }
        )
    return {"items": items}


@admin_router.post(
    "/users/status",
    summary="Активация, блокировка или смена роли пользователя",
    responses={**ADMIN_ERR, 404: err("Пользователь не найден (`user_not_found`)"), 409: err("Нельзя заблокировать или понизить собственную учётку (`self_change`)")},
)
def admin_user_status(
    data: AdminUserStatusIn,
    actor: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    u = db.get(User, data.user_id)
    if u is None:
        raise api_error(404, "user_not_found", "Пользователь не найден")
    if u.id == actor.id and (data.is_active is False or (data.role and data.role != UserRole.admin)):
        raise api_error(409, "self_change", "Нельзя заблокировать или снять права со своей учётной записи")
    if data.is_active is not None:
        u.is_active = data.is_active
        if not data.is_active:
            u.token_version = (u.token_version or 0) + 1
    if data.role is not None:
        u.role = data.role
        u.token_version = (u.token_version or 0) + 1
    db.commit()
    return {"id": str(u.id), "email": u.email, "role": u.role.value, "is_active": u.is_active}


@admin_router.get("/companies", summary="Список компаний и их текущих тарифов", responses=ADMIN_ERR)
def admin_companies(
    include_demo: bool = Query(False),
    q: str | None = Query(None, max_length=100),
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Company)
    if not include_demo:
        stmt = stmt.where(Company.is_demo.is_(False))
    if q and q.strip():
        stmt = stmt.where(Company.name.ilike(f"%{q.strip()}%"))
    rows = db.scalars(stmt.order_by(Company.created_at.desc()).limit(100)).all()
    items = []
    for c in rows:
        pid, partner, r = tariff_svc.effective(db, c)
        items.append(
            {
                "id": str(c.id),
                "name": c.name,
                "city": c.city,
                "industry": c.industry,
                "inn": c.inn,
                "contact_email": c.contact_email,
                "is_demo": c.is_demo,
                "plan_id": pid,
                "plan_title": tariff_plans.plan(pid)["title"],
                "fsp_partner": partner,
                "partner_note": r.partner_note if r else None,
                "partner_requested_at": as_aware(r.partner_requested_at).isoformat() if r and r.partner_requested_at else None,
                "partner_request_note": r.partner_request_note if r else None,
                "created_at": as_aware(c.created_at).isoformat(),
            }
        )
    return {"items": items}


@admin_router.post(
    "/companies/tariff",
    summary="Включить или изменить тариф компании («Старт», «Найм», «Партнёр ФСП»)",
    responses={**ADMIN_ERR, 404: err("Компания не найдена (`company_not_found`)")},
)
def admin_set_company_tariff(
    data: AdminCompanyTariffIn,
    actor: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    c = db.get(Company, data.company_id)
    if c is None:
        raise api_error(404, "company_not_found", "Компания не найдена")
    _apply_company_tariff(db, c, data.plan, actor, data.note)
    for req in db.scalars(
        select(TariffRequest).where(TariffRequest.company_id == c.id, TariffRequest.status == "pending")
    ).all():
        req.status = "approved"
        req.admin_note = data.note or f"Подключён тариф «{tariff_plans.plan(data.plan)['title']}»"
        req.resolved_by = actor.id
        req.resolved_at = utcnow()
    db.commit()
    pid, partner, r = tariff_svc.effective(db, c)
    return {
        "company_id": str(c.id),
        "name": c.name,
        "plan_id": pid,
        "plan_title": tariff_plans.plan(pid)["title"],
        "fsp_partner": partner,
        "partner_note": r.partner_note if r else None,
    }


@admin_router.get("/requests", summary="Все заявки на тарифы, партнёрство ФСП и обращения в поддержку", responses=ADMIN_ERR)
def admin_requests(
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    t_reqs = db.scalars(select(TariffRequest).order_by(TariffRequest.created_at.desc()).limit(100)).all()
    s_tickets = db.scalars(select(SupportTicket).order_by(SupportTicket.created_at.desc()).limit(100)).all()
    p_rows = db.scalars(
        select(CompanyTariff).where(
            CompanyTariff.fsp_partner.is_(False),
            CompanyTariff.partner_requested_at.is_not(None),
        )
    ).all()
    partner_requests = []
    for r in p_rows:
        c = db.get(Company, r.company_id)
        if c is not None:
            partner_requests.append(
                {
                    "company_id": str(c.id),
                    "company_name": c.name,
                    "contact_email": c.contact_email,
                    "requested_at": as_aware(r.partner_requested_at).isoformat() if r.partner_requested_at else None,
                    "note": r.partner_request_note,
                    "is_demo": c.is_demo,
                }
            )
    return {
        "tariff_requests": [_tariff_req_out(x) for x in t_reqs],
        "partner_requests": partner_requests,
        "support_tickets": [_ticket_out(x) for x in s_tickets],
    }


@admin_router.post(
    "/requests/tariff-resolve",
    summary="Одобрить (с включением тарифа компании) или отклонить заявку на тариф",
    responses={**ADMIN_ERR, 404: err("Заявка не найдена (`request_not_found`)")},
)
def admin_resolve_tariff_request(
    data: AdminTariffResolveIn,
    actor: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    req = db.get(TariffRequest, data.request_id)
    if req is None:
        raise api_error(404, "request_not_found", "Заявка на тариф не найдена")
    req.status = "approved" if data.action == "approve" else "rejected"
    req.admin_note = (data.admin_note or "").strip() or None
    req.resolved_by = actor.id
    req.resolved_at = utcnow()

    company: Company | None = db.get(Company, req.company_id) if req.company_id else None
    if company is None and req.company_name:
        company = db.scalar(select(Company).where(Company.name == req.company_name))
    if data.action == "approve" and company is not None:
        req.company_id = company.id
        _apply_company_tariff(db, company, req.plan, actor, req.admin_note)

    db.commit()
    db.refresh(req)
    status_word = "одобрена и тариф активирован" if data.action == "approve" else "отклонена"
    _send_mail_safe(
        req.contact_email,
        f"Заявка на тариф «{tariff_plans.plan(req.plan)['title']}» {status_word}",
        f"Здравствуйте!\n\nВаша заявка на тариф «{tariff_plans.plan(req.plan)['title']}» для компании «{req.company_name}» {status_word}.\n"
        + (f"Комментарий администратора: {req.admin_note}\n" if req.admin_note else ""),
    )
    return {"request": _tariff_req_out(req)}


@admin_router.post(
    "/requests/support-resolve",
    summary="Ответить на обращение в поддержку и закрыть/решить его",
    responses={**ADMIN_ERR, 404: err("Обращение не найдено (`ticket_not_found`)")},
)
def admin_resolve_support_ticket(
    data: AdminSupportResolveIn,
    actor: User = Depends(admin_only),
    db: Session = Depends(get_db),
) -> dict:
    ticket = db.get(SupportTicket, data.ticket_id)
    if ticket is None:
        raise api_error(404, "ticket_not_found", "Обращение не найдено")
    ticket.status = data.status
    if data.admin_reply is not None:
        ticket.admin_reply = data.admin_reply.strip() or None
    ticket.resolved_by = actor.id
    ticket.resolved_at = utcnow()
    db.commit()
    db.refresh(ticket)
    if ticket.admin_reply:
        _send_mail_safe(
            ticket.email,
            f"Ответ службы поддержки: {ticket.subject}",
            f"Здравствуйте!\n\nПо вашему обращению «{ticket.subject}» получен ответ:\n\n{ticket.admin_reply}",
        )
    return {"ticket": _ticket_out(ticket)}


@admin_router.get("/flags", summary="Состояние переключателей режима жюри и функций платформы", responses=ADMIN_ERR)
def admin_get_flags(_: User = Depends(admin_only)) -> dict:
    return _flags_state()


@admin_router.post("/flags", summary="Переключить демо-режим жюри (jury_mode) без перезапуска сервера", responses=ADMIN_ERR)
def admin_set_flags(data: AdminFlagsIn, _: User = Depends(admin_only)) -> dict:
    import app.core.flags as flags_mod

    flag_file = Path(os.environ.get("JURY_OFF_FLAG", "/tmp/spectrek_jury_off"))
    try:
        if data.jury_mode:
            for p in flags_mod._PATHS:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass
        else:
            flag_file.parent.mkdir(parents=True, exist_ok=True)
            flag_file.write_text("off\n", encoding="utf-8")
    except OSError:
        Path("/tmp/spectrek_jury_off").write_text("off\n", encoding="utf-8")
    flags_mod._cache = (0.0, not data.jury_mode)
    return _flags_state()
