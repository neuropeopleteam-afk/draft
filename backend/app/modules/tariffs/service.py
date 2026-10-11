"""Тарифы работодателя: действующий тариф компании, лимит приглашений в месяц, функции, демо-счёт, «Партнёр ФСП».

Всё работает только при TARIFFS_ENABLED (по умолчанию выключено): без флага лимит не проверяется, функции не
ограничиваются, ответы API других модулей не меняются (badge() — пустой словарь), методы тарифов отвечают 404
tariffs_disabled.

Месяц лимита — календарный по Москве (UTC+3, без перехода на летнее время). В лимит идут все приглашения компании,
созданные с 1-го числа: отозванное приглашение лимит не возвращает (иначе «отправил — отозвал» обходит лимит).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
import secrets
import uuid

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import as_aware, get_db, utcnow
from app.core.enums import UserRole
from app.core.errors import api_error
from app.modules.auth.models import User
from app.modules.invitations.models import Invitation
from app.modules.profiles.models import Company, EmployerProfile
from app.modules.tariffs import plans as P
from app.modules.tariffs.models import CompanyTariff, DemoInvoice

MSK = timezone(timedelta(hours=3))


def enabled() -> bool:
    return bool(get_settings().tariffs_enabled)


def need_on() -> None:
    if not enabled():
        raise api_error(404, "tariffs_disabled", "Тарифы не включены на этом сервере")


def meta() -> dict:
    """Для /api/meta: показывать ли раздел «Тарифы», счётчик приглашений и метку партнёра."""
    return {"enabled": enabled(), "price_is_stub": P.PRICE_IS_STUB}


# ------------------------------------------------------------------ тариф компании

def _jury_default(c: Company) -> str | None:
    return P.JURY_DEFAULTS.get(c.name) if c.is_demo else None


def row_of(db: Session, company_id: uuid.UUID) -> CompanyTariff | None:
    return db.get(CompanyTariff, company_id)


def ensure_row(db: Session, c: Company) -> CompanyTariff:
    """Строка тарифа компании; новая — со значениями по умолчанию (у песочниц жюри — свои, plans.JURY_DEFAULTS)."""
    r = row_of(db, c.id)
    if r is None:
        jd = _jury_default(c)
        r = CompanyTariff(company_id=c.id, plan="hire" if jd in ("hire", "partner") else P.DEFAULT_PLAN,
                          plan_since=utcnow(), fsp_partner=jd == "partner",
                          partner_since=utcnow() if jd == "partner" else None,
                          partner_note="Демо: партнёр ФСП в песочнице жюри" if jd == "partner" else None)
        db.add(r)
        db.flush()
    return r


def effective(db: Session, c: Company) -> tuple[str, bool, CompanyTariff | None]:
    """(id действующего тарифа, партнёр ли ФСП, строка или None — значения по умолчанию)."""
    r = row_of(db, c.id)
    if r is None:
        jd = _jury_default(c) or P.DEFAULT_PLAN
        return jd, jd == "partner", None
    return ("partner" if r.fsp_partner else r.plan), bool(r.fsp_partner), r


def is_partner(db: Session, company_id: uuid.UUID) -> bool:
    c = db.get(Company, company_id)
    return bool(c and effective(db, c)[1])


def badge(db: Session, company_id: uuid.UUID | None) -> dict:
    """Поле метки для ответов других модулей: пусто без флага — ответ API прежний."""
    if not enabled() or company_id is None:
        return {}
    return {"fsp_partner": is_partner(db, company_id)}


def month_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Начало текущего календарного месяца по Москве и начало следующего (в UTC)."""
    n = (as_aware(now) or utcnow()).astimezone(MSK)
    start = n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start.astimezone(UTC), nxt.astimezone(UTC)


def invites_used(db: Session, company_id: uuid.UUID, now: datetime | None = None) -> int:
    start, _ = month_window(now)
    return int(db.scalar(select(func.count(Invitation.id)).where(Invitation.company_id == company_id,
                                                                 Invitation.created_at >= start)) or 0)


def usage(db: Session, c: Company, now: datetime | None = None) -> dict:
    pid, _, _ = effective(db, c)
    limit = P.plan(pid)["invites_per_month"]
    used = invites_used(db, c.id, now)
    start, nxt = month_window(now)
    return {"month": start.astimezone(MSK).strftime("%Y-%m"), "invites_used": used, "invites_limit": limit,
            "invites_left": max(0, limit - used), "resets_at": nxt.isoformat(),
            "resets_on": nxt.astimezone(MSK).strftime("%d.%m.%Y")}


def _upsell(pid: str) -> str:
    if pid == "start":
        h = P.plan("hire")
        return (f" Больше приглашений — в тарифе «{h['title']}» ({h['invites_per_month']} в месяц): раздел «Тарифы» "
                "кабинета работодателя.")
    if pid == "hire":
        return " Партнёрам ФСП — до 100 приглашений в месяц: заявка в разделе «Тарифы»."
    return ""


def check_invite_limit(db: Session, c: Company) -> None:
    """Перед отправкой приглашения: лимит тарифа в месяц. Без TARIFFS_ENABLED — ничего не проверяет."""
    if not enabled():
        return
    pid, _, _ = effective(db, c)
    u = usage(db, c)
    if u["invites_used"] >= u["invites_limit"]:
        raise api_error(409, "tariff_limit",
                        f"В тарифе «{P.plan(pid)['title']}» — {u['invites_limit']} приглашений в месяц, все использованы. "
                        f"Следующие — с {u['resets_on']}.{_upsell(pid)}")


def feature_allowed(db: Session, c: Company, feature: str) -> bool:
    if not enabled():
        return True
    return bool(P.plan(effective(db, c)[0])["features"].get(feature))


def require_feature(feature: str):
    """Зависимость FastAPI для методов работодателя: функция тарифа (ats, assignments, salary_market). Без флага,
    без профиля компании или не для работодателя — пропускает (права и компанию проверяет сам метод)."""
    from app.core.deps import get_current_user

    def dep(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
        if not enabled() or user.role != UserRole.employer:
            return
        ep = db.get(EmployerProfile, user.id)
        c = db.get(Company, ep.company_id) if ep and ep.company_id else None
        if c is None or feature_allowed(db, c, feature):
            return
        title = P.FEATURES.get(feature, feature)
        raise api_error(403, "tariff_feature",
                        f"{title} — в тарифах «Найм» и «Партнёр ФСП». Сменить тариф — раздел «Тарифы» кабинета.")

    return dep


# ------------------------------------------------------------------ состояние для кабинета и смена тарифа

def invoice_out(i: DemoInvoice) -> dict:
    return {"id": str(i.id), "number": i.number, "plan": i.plan, "plan_title": P.plan(i.plan)["title"],
            "amount_rub": i.amount_rub, "vat_rub": i.vat_rub, "vat_rate": P.VAT_RATE,
            "period_from": i.period_from.isoformat(), "period_to": i.period_to.isoformat(), "status": i.status,
            "created_at": as_aware(i.created_at).isoformat(),
            "note": "Демонстрационный счёт: оплата не проводится, тариф подключён сразу."}


def state(db: Session, c: Company) -> dict:
    pid, partner, r = effective(db, c)
    invs = db.scalars(select(DemoInvoice).where(DemoInvoice.company_id == c.id)
                      .order_by(DemoInvoice.created_at.desc()).limit(5)).all()
    return {"enabled": True, "plan_id": pid, "plan": next(p for p in P.public_plans() if p["id"] == pid),
            "chosen_plan_id": r.plan if r else ("hire" if pid == "partner" else pid),
            "is_default": r is None, "fsp_partner": partner,
            "partner_since": as_aware(r.partner_since).isoformat() if r and r.partner_since else None,
            "partner_note": r.partner_note if r else None,
            "partner_requested_at": (as_aware(r.partner_requested_at).isoformat()
                                     if r and r.partner_requested_at and not r.fsp_partner else None),
            "usage": usage(db, c), "invoices": [invoice_out(i) for i in invs],
            "plans": P.public_plans(), "price_is_stub": P.PRICE_IS_STUB}


def _invoice_number(db: Session) -> str:
    for _ in range(5):
        n = f"Д-{utcnow().astimezone(MSK):%Y%m}-{secrets.token_hex(3).upper()}"
        if db.scalar(select(DemoInvoice.id).where(DemoInvoice.number == n)) is None:
            return n
    return f"Д-{uuid.uuid4().hex[:12].upper()}"


def choose(db: Session, c: Company, user: User, plan_id: str) -> dict:
    """Работодатель выбирает «Старт» или «Найм». «Найм» — демо-счёт и подключение сразу; «Партнёр ФСП» не выбирается."""
    if plan_id == "partner":
        raise api_error(409, "partner_by_fsp", "Тариф «Партнёр ФСП» подключает федерация по спонсорскому договору — "
                                               "отправьте заявку в разделе «Тарифы»")
    if plan_id not in ("start", "hire"):
        raise api_error(422, "plan_unknown", "Нет такого тарифа")
    pid, partner, _ = effective(db, c)
    if partner:
        raise api_error(409, "partner_active", "Действует тариф «Партнёр ФСП» — его условия шире, менять не нужно")
    if pid == plan_id:
        raise api_error(409, "plan_same", f"Тариф «{P.plan(plan_id)['title']}» уже подключён")
    r = ensure_row(db, c)
    invoice = None
    if plan_id == P.PAID_PLAN:
        p = P.plan(plan_id)
        today = utcnow().astimezone(MSK).date()
        invoice = DemoInvoice(company_id=c.id, number=_invoice_number(db), plan=plan_id, amount_rub=p["price_rub_month"],
                              vat_rub=P.vat_of(p["price_rub_month"]), period_from=today,
                              period_to=today + timedelta(days=30), status="demo", created_by=user.id)
        db.add(invoice)
    r.plan = plan_id
    r.plan_since = utcnow()
    r.changed_by = user.id
    db.commit()
    out = state(db, c)
    out["invoice"] = invoice_out(invoice) if invoice else None
    return out


def request_partner(db: Session, c: Company, note: str | None) -> dict:
    r = ensure_row(db, c)
    if r.fsp_partner:
        raise api_error(409, "partner_already", "Компания уже партнёр ФСП")
    r.partner_requested_at = utcnow()
    r.partner_request_note = (note or "").strip()[:500] or None
    db.commit()
    return state(db, c)


# ------------------------------------------------------------------ ФСП: метка партнёра

def _jury_sid(email: str | None) -> str | None:
    from app.modules.jury import scope as jury_scope

    persona, sid = jury_scope.parse(email)
    return None if persona is None else sid


def can_manage(db: Session, actor: User, c: Company) -> bool:
    """Учётка жюри с ролью «ФСП» меняет метку только у компаний своей песочницы (общие демо и чужие — только смотреть);
    настоящий аналитик ФСП и администратор — у любой компании, кроме песочниц жюри."""
    owner = db.get(User, c.created_by) if c.created_by else None
    a_sid, o_sid = _jury_sid(actor.email), _jury_sid(owner.email if owner else None)
    if a_sid is not None:
        return o_sid is not None and o_sid == a_sid
    return o_sid is None


def set_partner(db: Session, actor: User, c: Company, grant: bool, note: str | None) -> CompanyTariff:
    if not can_manage(db, actor, c):
        raise api_error(403, "partner_scope", "Метку этой компании меняет другой кабинет ФСП")
    r = ensure_row(db, c)
    r.fsp_partner = grant
    if grant:
        r.partner_since = utcnow()
        r.partner_granted_by = actor.id
        r.partner_note = (note or "").strip()[:300] or r.partner_note
        r.partner_requested_at = None
    else:
        r.partner_since = None
        r.partner_granted_by = None
    db.commit()
    return r


def company_brief(db: Session, c: Company, actor: User | None = None) -> dict:
    pid, partner, r = effective(db, c)
    return {"company_id": str(c.id), "name": c.name, "city": c.city, "industry": c.industry, "inn": c.inn,
            "is_demo": c.is_demo, "plan_id": pid, "plan_title": P.plan(pid)["title"], "fsp_partner": partner,
            "partner_since": as_aware(r.partner_since).isoformat() if r and r.partner_since else None,
            "partner_note": r.partner_note if r else None,
            "requested_at": as_aware(r.partner_requested_at).isoformat() if r and r.partner_requested_at else None,
            "request_note": r.partner_request_note if r and r.partner_requested_at else None,
            "can_manage": can_manage(db, actor, c) if actor else False}


def _visible(db: Session, actor: User, c: Company) -> bool:
    """Аналитик видит компании платформы без песочниц жюри; жюри — ещё и компании своей песочницы."""
    owner = db.get(User, c.created_by) if c.created_by else None
    o_sid = _jury_sid(owner.email if owner else None)
    return o_sid is None or o_sid == _jury_sid(actor.email)


def partners_overview(db: Session, actor: User) -> dict:
    rows = db.scalars(select(CompanyTariff).where((CompanyTariff.fsp_partner.is_(True))
                                                  | (CompanyTariff.partner_requested_at.is_not(None)))).all()
    seen = {r.company_id for r in rows}
    comps = [db.get(Company, r.company_id) for r in rows]
    # компании песочницы жюри без строки тарифа (партнёр по умолчанию) — тоже видны своему кабинету
    if _jury_sid(actor.email) is not None:
        for c in db.scalars(select(Company).where(Company.is_demo.is_(True),
                                                  Company.name.in_(list(P.JURY_DEFAULTS)))).all():
            if c.id not in seen and effective(db, c)[1]:
                comps.append(c)
    items = [company_brief(db, c, actor) for c in comps if c is not None and _visible(db, actor, c)]
    partners = sorted([i for i in items if i["fsp_partner"]], key=lambda i: i["name"])
    requests = sorted([i for i in items if not i["fsp_partner"] and i["requested_at"]], key=lambda i: i["requested_at"])
    return {"partners": partners, "requests": requests}


def search_companies(db: Session, actor: User, q: str) -> list[dict]:
    q = q.strip()
    if len(q) < 3:
        return []
    like = f"%{q.replace('%', '').replace('_', ' ')}%"  # ilike: в PostgreSQL без учёта регистра и для кириллицы
    rows = db.scalars(select(Company).where(Company.name.ilike(like) | (Company.inn == q))
                      .order_by(Company.name).limit(30)).all()
    return [company_brief(db, c, actor) for c in rows if _visible(db, actor, c)][:10]


def plans_distribution(db: Session, company_ids: set) -> dict:
    """Сколько компаний на каком тарифе (без песочниц жюри — их отсекает вызывающий)."""
    out = {p["id"]: 0 for p in P.PLANS}
    for cid in company_ids:
        c = db.get(Company, cid)
        if c is not None:
            out[effective(db, c)[0]] += 1
    return out


def today_msk() -> date:
    return utcnow().astimezone(MSK).date()
