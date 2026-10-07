"""Индекс доверия работодателя (0–100) с понятными причинами — виден кандидату в приглашении и профиле компании.

Признаки и максимальные баллы (сумма 100):

| Признак | Макс. | Откуда |
|---|---|---|
| Компания найдена в ЕГРЮЛ/ЕГРИП и действует | 30 | egrul.nalog.ru (кэш 7 дней) |
| Возраст компании (дата регистрации) | 15 | ЕГРЮЛ: ≥ 3 лет — 15, ≥ 1 года — 10, ≥ 3 мес. — 5 |
| Название в профиле совпадает с ЕГРЮЛ | 5 | ЕГРЮЛ |
| Корпоративная почта на домене сайта компании | 15 | почта работодателя vs сайт |
| Реалистичность вилок относительно рынка категории | 15 | приглашения и вакансии vs p25–p75 Хабр Карьеры |
| Доля принятых приглашений | 10 | история приглашений |
| Скорость ответа работодателя | 10 | отклики и зонды |
| Жалобы кандидатов на приглашения | штраф до −25 | нереальная вилка, не та роль, спам — за 180 дней |

Ликвидированная компания или ИНН, которого нет в реестре, — индекс не выше 10 («низкий»).
Если ФНС не ответила (капча, сбой) — признак «не удалось проверить», индекс помечается как предварительный.
Мало данных по поведению (меньше 3 ответов) — нейтрально: половина баллов, без штрафа.
Жалобы: −5 за каждого пожаловавшегося кандидата (не больше −25); три и больше жалоб на 30 % приглашений и
выше — признак «плохо». Жаловаться может только приглашённый кандидат, одна жалоба на приглашение.
"""
from __future__ import annotations

from datetime import timedelta
import re
from statistics import median
from urllib.parse import urlparse

from sqlalchemy import func as sa_func, select
from sqlalchemy.orm import Session

from app.core.db import as_aware, utcnow
from app.core.enums import InvitationStatus, ProbeStatus
from app.integrations.egrul.client import age_years, check_inn
from app.integrations.egrul.models import RegistryCheck
from app.integrations.vacancies.models import Vacancy, VacancyApplication
from app.modules.auth.models import User
from app.modules.catalog.models import Category
from app.modules.invitations.models import Invitation, InvitationComplaint, Probe
from app.modules.profiles.models import CandidateProfile, Company, EmployerProfile

FREE_MAIL = {
    "gmail.com", "googlemail.com", "mail.ru", "bk.ru", "inbox.ru", "list.ru", "internet.ru", "yandex.ru", "ya.ru",
    "yandex.com", "yandex.by", "yandex.kz", "rambler.ru", "outlook.com", "hotmail.com", "live.com", "icloud.com",
    "me.com", "yahoo.com", "proton.me", "protonmail.com", "gmx.com", "mail.com", "zoho.com",
}
LEVELS = [(75, "high", "Высокий"), (50, "medium", "Средний"), (0, "low", "Низкий")]
# Вилка правдоподобна, если верх не выше 2× верха рынка, а низ не ниже 0,5× низа рынка категории
SALARY_HIGH_X, SALARY_LOW_X = 2.0, 0.5


def _domain_of_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[1].strip().lower()


def _domain_of_site(site: str | None) -> str | None:
    if not site:
        return None
    s = site.strip().lower()
    if "://" not in s:
        s = "http://" + s
    host = (urlparse(s).hostname or "").removeprefix("www.")
    return host or None


def domains_match(email_domain: str, site_domain: str) -> bool:
    return (email_domain == site_domain or email_domain.endswith("." + site_domain)
            or site_domain.endswith("." + email_domain))


def _norm_name(s: str | None) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"общество с ограниченной ответственностью|публичное акционерное общество|"
               r"акционерное общество|индивидуальный предприниматель|\b(ооо|пао|ао|зао|оао|ип|llc|ltd)\b", " ", s)
    return " ".join(re.findall(r"[a-zа-я0-9]+", s))


def names_match(ours: str | None, registry: list[str | None]) -> bool:
    a = _norm_name(ours)
    if not a:
        return False
    for r in registry:
        b = _norm_name(r)
        if b and (a == b or a in b or b in a):
            return True
    return False


def _factor(fid: str, title: str, status: str, points: float, max_points: int, text: str) -> dict:
    return {"id": fid, "title": title, "status": status, "points": round(points, 1), "max": max_points, "text": text}


def _rub(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " ₽"


def salary_check(salary_from: int, salary_to: int, cat: Category | None,
                 basis: str | None = "gross") -> tuple[str, str]:
    """(status, текст) для одной вилки относительно рыночного диапазона категории. Рынок (Хабр Карьера) — на руки,
    поэтому вилка до вычета НДФЛ сравнивается после пересчёта (app.modules.contact.salary)."""
    from app.modules.contact.salary import to_net

    if cat is None:
        return "unknown", "категория неизвестна — сравнить не с чем"
    lo, hi = cat.market_salary_from, cat.market_salary_to
    rng = f"рынок {cat.title} на руки: {_rub(lo)} – {_rub(hi)}"
    f_net, t_net = to_net(salary_from, basis), to_net(salary_to, basis)
    gross = (basis or "gross") == "gross"
    note = f" до вычета НДФЛ, ≈ {_rub(f_net)} – {_rub(t_net)} на руки" if gross else " на руки"
    if t_net > SALARY_HIGH_X * hi:
        return "warn", (f"верх вилки {_rub(salary_to)}{' (≈ ' + _rub(t_net) + ' на руки)' if gross else ''} больше "
                        f"чем вдвое выше рынка ({rng}) — так бывает в вакансиях-приманках")
    if f_net < SALARY_LOW_X * lo:
        return "warn", (f"низ вилки {_rub(salary_from)}{' (≈ ' + _rub(f_net) + ' на руки)' if gross else ''} "
                        f"заметно ниже рынка ({rng})")
    return "ok", f"вилка {_rub(salary_from)} – {_rub(salary_to)}{note} в разумных пределах ({rng})"


def registry_factors(chk: RegistryCheck | None, company: Company) -> tuple[list[dict], dict, bool, bool]:
    """Признаки ЕГРЮЛ → (факторы, сводка, предварительный ли индекс, критичный ли провал)."""
    if company.is_demo and not company.inn:
        f = [_factor("registry", "Сведения ФНС", "unknown", 0, 30, "демо-компания: проверка в ФНС не выполнялась"),
             _factor("age", "Возраст компании", "unknown", 0, 15, "нет сведений ФНС"),
             _factor("name", "Название совпадает с ЕГРЮЛ", "unknown", 0, 5, "нет сведений ФНС")]
        return f, {"status": "demo"}, True, False
    if not company.inn:
        f = [_factor("registry", "Сведения ФНС", "warn", 0, 30, "работодатель не указал ИНН"),
             _factor("age", "Возраст компании", "unknown", 0, 15, "нет ИНН — дата регистрации неизвестна"),
             _factor("name", "Название совпадает с ЕГРЮЛ", "unknown", 0, 5, "нет ИНН")]
        return f, {"status": "no_inn"}, False, False
    if chk is None:
        f = [_factor("registry", "Сведения ФНС", "unknown", 0, 30, "проверка ФНС ещё не выполнялась"),
             _factor("age", "Возраст компании", "unknown", 0, 15, "ожидает проверки ФНС"),
             _factor("name", "Название совпадает с ЕГРЮЛ", "unknown", 0, 5, "ожидает проверки ФНС")]
        return f, {"status": "pending", "inn": company.inn}, True, False
    summary = {"status": chk.status, "inn": chk.inn, "checked_at": chk.checked_at.isoformat(),
               "source": "egrul.nalog.ru", "source_url": "https://egrul.nalog.ru/", **(chk.data or {})}
    if chk.status in ("captcha", "error"):
        f = [_factor("registry", "Сведения ФНС", "unknown", 0, 30,
                     f"не удалось проверить: {chk.error or 'сервис ФНС не ответил'}; повторим позже"),
             _factor("age", "Возраст компании", "unknown", 0, 15, "не удалось проверить"),
             _factor("name", "Название совпадает с ЕГРЮЛ", "unknown", 0, 5, "не удалось проверить")]
        return f, summary, True, False
    if chk.status in ("not_found", "invalid"):
        why = "ИНН с неверной контрольной суммой" if chk.status == "invalid" else "по ИНН нет записи в ЕГРЮЛ/ЕГРИП"
        f = [_factor("registry", "Сведения ФНС", "bad", 0, 30, why),
             _factor("age", "Возраст компании", "unknown", 0, 15, "нет сведений ФНС"),
             _factor("name", "Название совпадает с ЕГРЮЛ", "unknown", 0, 5, "нет сведений ФНС")]
        return f, summary, False, True
    d = chk.data or {}
    out = []
    if d.get("liquidated_at"):
        out.append(_factor("registry", "Сведения ФНС", "bad", 0, 30,
                           f"компания прекратила деятельность {d['liquidated_at']} (ЕГРЮЛ)"))
        critical = True
    else:
        who = f"{d.get('director_role') or 'Руководитель'}: {d['director']}" if d.get("director") else "руководитель не указан"
        out.append(_factor("registry", "Сведения ФНС", "ok", 30, 30,
                           f"{d.get('short_name') or d.get('name')} действует, ОГРН {d.get('ogrn')}; {who}"))
        critical = False
    age = age_years(d.get("registered_at"))
    summary["age_years"] = age
    if age is None:
        out.append(_factor("age", "Возраст компании", "unknown", 0, 15, "дата регистрации не указана"))
    else:
        pts = 15 if age >= 3 else 10 if age >= 1 else 5 if age >= 0.25 else 0
        st = "ok" if age >= 1 else "warn"
        when = f"зарегистрирована {d['registered_at'][8:10]}.{d['registered_at'][5:7]}.{d['registered_at'][:4]}"
        txt = f"{when} ({age:g} г.)" if age >= 1 else f"{when} — компании меньше года"
        out.append(_factor("age", "Возраст компании", st, pts, 15, txt))
    if names_match(company.name, [d.get("name"), d.get("short_name")]):
        out.append(_factor("name", "Название совпадает с ЕГРЮЛ", "ok", 5, 5, f"«{company.name}» совпадает с реестром"))
    else:
        out.append(_factor("name", "Название совпадает с ЕГРЮЛ", "warn", 0, 5,
                           f"в профиле «{company.name}», в реестре «{d.get('short_name') or d.get('name')}»"))
    return out, summary, False, critical


def email_factor(db: Session, company: Company) -> dict:
    site = _domain_of_site(company.website)
    emails = [u.email for u in db.scalars(select(User).join(EmployerProfile, EmployerProfile.user_id == User.id)
                                          .where(EmployerProfile.company_id == company.id)).all()]
    if company.contact_email:
        emails.append(company.contact_email)
    domains = sorted({d for d in (_domain_of_email(e) for e in emails) if d})
    if not domains:
        return _factor("email", "Корпоративная почта", "unknown", 0, 15, "почта работодателя не указана")
    corp = [d for d in domains if d not in FREE_MAIL]
    if not site:
        if corp:
            return _factor("email", "Корпоративная почта", "warn", 7, 15,
                           f"почта на домене {corp[0]}, но сайт компании не указан — сверить не с чем")
        return _factor("email", "Корпоративная почта", "warn", 0, 15,
                       f"почта на бесплатном сервисе ({domains[0]}), сайт не указан")
    if any(domains_match(d, site) for d in corp):
        return _factor("email", "Корпоративная почта", "ok", 15, 15, f"почта работодателя на домене сайта {site}")
    if corp:
        return _factor("email", "Корпоративная почта", "warn", 3, 15,
                       f"домен почты ({corp[0]}) не совпадает с сайтом компании ({site})")
    return _factor("email", "Корпоративная почта", "warn", 0, 15,
                   f"почта на бесплатном сервисе ({domains[0]}), а не на домене сайта {site}")


def salary_factor(db: Session, company: Company, cats: dict[str, Category]) -> tuple[dict, list[dict]]:
    since = utcnow() - timedelta(days=180)
    checks = []
    for inv in db.scalars(select(Invitation).where(Invitation.company_id == company.id,
                                                   Invitation.created_at > since)).all():
        cp = db.get(CandidateProfile, inv.candidate_user_id)
        st, txt = salary_check(inv.salary_from, inv.salary_to, cats.get(cp.current_category_id) if cp else None,
                               inv.salary_basis)
        checks.append({"kind": "invitation", "title": inv.position_title, "status": st, "text": txt})
    for v in db.scalars(select(Vacancy).where(Vacancy.company_id == company.id, Vacancy.status != "draft")).all():
        st, txt = salary_check(v.salary_from, v.salary_to, cats.get(v.category_id), v.salary_basis)
        checks.append({"kind": "vacancy", "title": v.title, "status": st, "text": txt})
    known = [c for c in checks if c["status"] != "unknown"]
    if not known:
        return _factor("salary", "Реалистичность вилок", "unknown", 7.5, 15,
                       "предложений с известной категорией пока нет — нейтрально"), checks
    bad = [c for c in known if c["status"] == "warn"]
    share_ok = 1 - len(bad) / len(known)
    pts = 15 * share_ok
    if not bad:
        return _factor("salary", "Реалистичность вилок", "ok", pts, 15,
                       (f"все вилки ({len(known)}) в пределах рынка категорий" if len(known) > 1 else "вилка в пределах рынка категории")), checks
    return _factor("salary", "Реалистичность вилок", "warn", pts, 15,
                   f"{len(bad)} из {len(known)} вилок вне рынка: {bad[0]['text']}"), checks


def acceptance_factor(db: Session, company: Company) -> dict:
    rows = db.scalars(select(Invitation.status).where(Invitation.company_id == company.id)).all()
    acc = sum(1 for s in rows if s == InvitationStatus.accepted)
    dec = sum(1 for s in rows if s == InvitationStatus.declined)
    n = acc + dec
    if n < 3:
        return _factor("acceptance", "Доля принятых приглашений", "unknown", 5, 10,
                       f"мало ответов кандидатов ({n}) — нейтрально")
    share = acc / n
    pct = round(100 * share)
    if share >= 0.3:
        return _factor("acceptance", "Доля принятых приглашений", "ok", 10, 10, f"кандидаты приняли {acc} из {n} ({pct} %)")
    if share >= 0.15:
        return _factor("acceptance", "Доля принятых приглашений", "ok", 6, 10, f"кандидаты приняли {acc} из {n} ({pct} %)")
    return _factor("acceptance", "Доля принятых приглашений", "warn", 2, 10,
                   f"кандидаты часто отказываются: принято {acc} из {n} ({pct} %)")


def speed_factor(db: Session, company: Company) -> dict:
    """Медиана времени до первой реакции работодателя: отклики (до просмотра/ответа) и зонды (до оценки)."""
    hours = []
    apps = db.scalars(select(VacancyApplication).join(Vacancy, Vacancy.id == VacancyApplication.vacancy_id)
                      .where(Vacancy.company_id == company.id)).all()
    now = utcnow()
    for a in apps:
        first = a.viewed_at or a.responded_at
        if first:
            hours.append((as_aware(first) - as_aware(a.created_at)).total_seconds() / 3600)
        elif a.status == "sent" and (now - as_aware(a.created_at)) > timedelta(days=7):
            hours.append((now - as_aware(a.created_at)).total_seconds() / 3600)  # без ответа больше недели
    for p in db.scalars(select(Probe).where(Probe.company_id == company.id, Probe.submitted_at.is_not(None))).all():
        reviewed = next((e.get("at") for e in (p.events or []) if e.get("status") == ProbeStatus.reviewed.value), None)
        if reviewed:
            from datetime import datetime

            hours.append((as_aware(datetime.fromisoformat(reviewed)) - as_aware(p.submitted_at)).total_seconds() / 3600)
    if len(hours) < 3:
        return _factor("speed", "Скорость ответа", "unknown", 5, 10, f"мало данных ({len(hours)}) — нейтрально")
    m = median(hours)
    when = f"{m:.0f} ч" if m >= 1 else "меньше часа"
    if m <= 48:
        return _factor("speed", "Скорость ответа", "ok", 10, 10, f"медиана ответа кандидатам — {when}")
    if m <= 168:
        return _factor("speed", "Скорость ответа", "ok", 5, 10, f"медиана ответа кандидатам — {m / 24:.0f} дн.")
    return _factor("speed", "Скорость ответа", "warn", 1, 10, f"отвечает медленно: медиана {m / 24:.0f} дн.")


COMPLAINT_PENALTY, COMPLAINT_MAX_PENALTY = 5, 25


def complaints_factor(db: Session, company: Company) -> dict:
    """Штраф за жалобы кандидатов на приглашения за 180 дней (баллы ≤ 0, максимум 0)."""
    from app.modules.invitations.service import COMPLAINT_REASONS

    since = utcnow() - timedelta(days=180)
    rows = db.scalars(select(InvitationComplaint).where(InvitationComplaint.company_id == company.id,
                                                        InvitationComplaint.created_at > since)).all()
    if not rows:
        return _factor("complaints", "Жалобы кандидатов", "ok", 0, 0, "жалоб на приглашения нет")
    people = {r.candidate_user_id for r in rows}
    sent = db.scalar(select(sa_func.count()).select_from(Invitation).where(
        Invitation.company_id == company.id, Invitation.created_at > since)) or 0
    by: dict[str, int] = {}
    for r in rows:
        by[r.reason] = by.get(r.reason, 0) + 1
    what = ", ".join(f"{COMPLAINT_REASONS.get(k, k).lower()} — {v}" for k, v in sorted(by.items(), key=lambda x: -x[1]))
    pen = min(COMPLAINT_MAX_PENALTY, COMPLAINT_PENALTY * len(people))
    share = len(rows) / sent if sent else 1.0
    status = "bad" if len(people) >= 3 and share >= 0.3 else "warn"
    return _factor("complaints", "Жалобы кандидатов", status, -pen, 0,
                   f"жалоб за полгода: {len(rows)} из {sent} приглашений ({what})")


def compute(db: Session, company: Company, *, invitation: Invitation | None = None,
            vacancy: Vacancy | None = None, refresh: bool = False) -> dict:
    """Индекс доверия компании; с invitation/vacancy — плюс отдельная оценка вилки этого предложения."""
    chk = None
    if company.inn:
        if refresh:
            chk = check_inn(db, company.inn, force=True, company_id=company.id)
        else:
            chk = db.scalar(select(RegistryCheck).where(RegistryCheck.inn == company.inn.strip()))
    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    factors, registry, preliminary, critical = registry_factors(chk, company)
    factors.append(email_factor(db, company))
    sal, salary_checks = salary_factor(db, company, cats)
    factors.append(sal)
    factors.append(acceptance_factor(db, company))
    factors.append(speed_factor(db, company))
    factors.append(complaints_factor(db, company))
    score = max(0, sum(f["points"] for f in factors))
    if critical:
        score = min(score, 10)
    score = round(score)
    level, title = next((lv, t) for th, lv, t in LEVELS if score >= th)
    offer = None
    if invitation is not None:
        cp = db.get(CandidateProfile, invitation.candidate_user_id)
        st, txt = salary_check(invitation.salary_from, invitation.salary_to,
                               cats.get(cp.current_category_id) if cp else None, invitation.salary_basis)
        offer = {"status": st, "text": txt}
    elif vacancy is not None:
        st, txt = salary_check(vacancy.salary_from, vacancy.salary_to, cats.get(vacancy.category_id),
                               vacancy.salary_basis)
        offer = {"status": st, "text": txt}
    reasons_bad = [f for f in factors if f["status"] in ("bad", "warn")]
    reasons_ok = [f for f in factors if f["status"] == "ok"]
    return {
        "company_id": str(company.id), "company_name": company.name, "score": score, "level": level,
        "level_title": title, "preliminary": preliminary, "critical": critical,
        "factors": factors, "registry": registry, "offer_salary": offer,
        "salary_checks": salary_checks[:10],
        "summary": (reasons_bad[0]["text"] if reasons_bad else (reasons_ok[0]["text"] if reasons_ok else "")),
        "computed_at": utcnow().isoformat(),
        "method": "trust-v1",
    }


def short(t: dict) -> dict:
    return {k: t[k] for k in ("score", "level", "level_title", "preliminary", "critical", "summary", "offer_salary")}
