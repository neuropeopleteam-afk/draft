"""Верифицированный профиль кандидата для ATS: одна структура → поля Talantix, «Потока», Хантфлоу и вебхука.

Что уходит: категория и грейд, подтверждённое тестом и заданиями (T1), паспорт ФСП и достижения из реестра (T2),
заявленное кандидатом (T0, помечено как заявленное), позиция и вилка принятого оффера, ссылка на PDF-профиль
(подписанная, без входа на платформу) и на карточку кандидата. Контакты — только уже раскрытые работодателю.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html
import re

import jwt

from app.core.fmt import quoted, ru_num
from app.core.origin import NO_FSP
from app.integrations.settings import get_isettings

PDF_LINK_DAYS = 180
FSP_SOURCE_TITLES = {"registry": "реестр ФСП", "keycloak": "ФСП ID", "demo": "демо-реестр ФСП"}
WORK_FORMAT_TITLES = {"remote": "удалённо", "office": "офис", "hybrid": "гибрид", "any": "любой формат"}


def _rub(v: int | None) -> str:
    return "—" if v is None else f"{v:,}".replace(",", " ") + " ₽"


# ------------------------------------------------------------------ подписанная ссылка на PDF-профиль

def pdf_token(company_id: str, candidate_user_id: str, days: int = PDF_LINK_DAYS) -> str:
    s = get_isettings()
    exp = datetime.now(timezone.utc) + timedelta(days=days)
    return jwt.encode({"p": "ats_pdf", "c": str(company_id), "u": str(candidate_user_id), "exp": exp},
                      f"ats-pdf:{s.jwt_secret}", algorithm="HS256")


def read_pdf_token(token: str) -> tuple[str, str] | None:
    try:
        d = jwt.decode(token, f"ats-pdf:{get_isettings().jwt_secret}", algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if d.get("p") != "ats_pdf":
        return None
    return d["c"], d["u"]


def pdf_url(company_id: str, candidate_user_id: str) -> str:
    return f"{get_isettings().public_base_url.rstrip('/')}/api/ats/profile/{pdf_token(company_id, candidate_user_id)}.pdf"


# ------------------------------------------------------------------ ФИО

PATRONYMIC = ("вич", "вна", "ична", "чна", "оглы", "кызы")
SURNAME = ("ов", "ев", "ёв", "ин", "ын", "ова", "ева", "ёва", "ина", "ына", "ский", "цкий", "ская", "цкая", "ко", "ук",
           "юк", "дзе", "швили", "ян", "их", "ых")


def split_fio(full_name: str | None) -> tuple[str | None, str | None, str | None]:
    """(фамилия, имя, отчество) из свободной строки: «Петров Иван Сергеевич», «Иван Сергеевич Петров», «Иван Петров»."""
    parts = (full_name or "").split()
    if not parts:
        return None, None, None
    if len(parts) == 1:
        return parts[0], "—", None
    low = [x.lower() for x in parts]
    if len(parts) >= 3:
        if low[2].endswith(PATRONYMIC):
            return parts[0], parts[1], " ".join(parts[2:])
        if low[1].endswith(PATRONYMIC):
            return parts[-1], parts[0], parts[1]
        return parts[0], parts[1], " ".join(parts[2:])
    if low[1].endswith(SURNAME) and not low[0].endswith(SURNAME):
        return parts[1], parts[0], None
    return parts[0], parts[1], None


def phone_digits(phone: str | None) -> str | None:
    """«+7 900 111-22-33» / «8 (900) 111-22-33» → «79001112233» (с кодом страны, как требует «Поток»)."""
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 11 and d.startswith("8"):
        d = "7" + d[1:]
    if len(d) == 10:
        d = "7" + d
    return d or None


# ------------------------------------------------------------------ профиль

def build(p: dict) -> dict:
    """Из тела ``vstrechny.candidate.v1`` (service.export_payload) — плоская структура для адаптеров ATS."""
    c, ctx = p["candidate"], p["context"]
    card = c.get("card") or {}
    ct = c.get("contacts") or {}
    last, first, middle = split_fio(ct.get("full_name"))
    test = card.get("test") or None
    fsp = card.get("fsp") or {}
    links = p.get("links") or {}
    base = (p.get("source") or {}).get("url") or get_isettings().public_base_url
    return {
        "ref": c["ref"],
        "full_name": ct.get("full_name"), "last_name": last, "first_name": first, "middle_name": middle,
        "email": ct.get("email"), "phone": ct.get("phone"), "telegram": (ct.get("telegram") or "").lstrip("@") or None,
        "category_id": c.get("category_id"), "category_title": c.get("category_title"),
        "direction_title": card.get("direction_title"), "grade_title": card.get("grade_title"),
        "rating_score": card.get("rating_score"),
        "context_type": ctx.get("type"), "position_title": ctx.get("position_title"),
        "salary_from": ctx.get("salary_from"), "salary_to": ctx.get("salary_to"),
        "accepted_at": ctx.get("accepted_at") or ctx.get("applied_at"), "cover_letter": ctx.get("cover_letter"),
        "evidence": [e for e in (ctx.get("evidence") or []) if e.get("text")],
        "test": test if test and test.get("theta") is not None else None,
        "skills": [s for s in (card.get("skills_confirmed") or []) if s.get("title")],
        "probes": [x for x in (card.get("probes") or []) if x.get("title")],
        "fsp": {"linked": bool(fsp.get("linked")), "hidden": bool(fsp.get("hidden")),
                "source": FSP_SOURCE_TITLES.get(fsp.get("source") or "", fsp.get("source")),
                "achievements": [a.get("text") for a in (fsp.get("achievements") or []) if a.get("text")]},
        "declared": {"stack": [s.get("title") for s in (card.get("stack_declared") or []) if s.get("title")],
                     "experience_years": card.get("experience_years"),
                     "work_format": WORK_FORMAT_TITLES.get(card.get("work_format") or "", card.get("work_format")),
                     "city": card.get("city")},
        "pdf_url": links.get("pdf"), "card_url": links.get("card") or f"{base}/employer/candidates/{c['ref']}",
        "platform": (p.get("source") or {}).get("platform") or "Встречный (спецтрек ФСП)",
    }


def offer_text(d: dict) -> str:
    what = "Принял приглашение" if d["context_type"] == "invitation" else "Откликнулся на вакансию"
    return f"{what} на платформе «Встречный»: «{d['position_title']}», вилка оффера {_rub(d['salary_from'])} – {_rub(d['salary_to'])}."


def test_line(d: dict) -> str | None:
    t = d["test"]
    if not t:
        return None
    s = f"Адаптивный тест: {t.get('correct')} из {t.get('answered')} верно, θ = {ru_num(t['theta'], sign=True)}"
    if t.get("se") is not None:
        s += f" ± {ru_num(t['se'])}"
    if t.get("date"):
        s += f" ({t['date']})"
    integ = t.get("integrity") or {}
    if integ.get("title"):
        s += f"; достоверность результата: {integ['title']}"
    return s


def title(d: dict) -> str:
    return " — ".join(x for x in (d["category_title"], d["position_title"]) if x) or f"Кандидат {d['ref']}"


def key_skills(d: dict) -> list[str]:
    return [s["title"] for s in d["skills"]][:30]


def sections(d: dict) -> list[tuple[str, list[str]]]:
    """Разделы профиля: (заголовок, строки). Общая основа для HTML и текста."""
    out: list[tuple[str, list[str]]] = []
    head = [f"Категория: {d['category_title'] or 'не присвоена'}", offer_text(d)]
    if d["rating_score"] is not None:
        head.append(f"Рейтинг в категории (по подтверждённому): {d['rating_score']:.2f}")
    out.append((f"Кандидат {d['ref']} · {d['platform']}", head))
    t1 = [x for x in [test_line(d)] if x]
    t1 += [f"Навык подтверждён заданиями: {s['title']}" + (f" ({round(s['score'] * 100)} %)" if s.get("score") is not None
                                                          else "") for s in d["skills"][:12]]
    t1 += [f"Зонд работодателя {quoted(x['title'])}: {x.get('verdict') or '—'}" for x in d["probes"][:5]]
    out.append(("Подтверждено (T1)", t1 or ["Подтверждений тестом пока нет"]))
    f = d["fsp"]
    if f["hidden"]:
        t2 = ["Кандидат скрыл блок ФСП"]
    elif not f["linked"]:
        t2 = ["Паспорт ФСП не привязан. " + NO_FSP]
    else:
        t2 = [f"Паспорт ФСП привязан, источник: {f['source']}"] + [f"ФСП: {a}" for a in f["achievements"][:5]]
        if not f["achievements"]:
            t2.append("Подтверждённых достижений в реестре нет")
    out.append(("Паспорт ФСП (T2)", t2))
    dc = d["declared"]
    t0 = []
    if dc["stack"]:
        t0.append("Стек: " + ", ".join(dc["stack"][:15]))
    if dc["experience_years"] is not None:
        t0.append(f"Опыт: {dc['experience_years']:g} лет")
    if dc["work_format"]:
        t0.append(f"Формат работы: {dc['work_format']}")
    if dc["city"]:
        t0.append(f"Город: {dc['city']}")
    if t0:
        out.append(("Заявлено кандидатом (T0)", t0))
    if d["evidence"]:
        out.append(("Почему выбран (из приглашения)", [f"[{e.get('level')}] {e['text']}" for e in d["evidence"][:8]]))
    if d["cover_letter"]:
        out.append(("Сопроводительное письмо", [d["cover_letter"]]))
    links = []
    if d["pdf_url"]:
        links.append(f"PDF-профиль: {d['pdf_url']}")
    links.append(f"Карточка на платформе: {d['card_url']}")
    out.append(("Ссылки", links))
    return out


def as_text(d: dict) -> str:
    lines: list[str] = []
    for h, rows in sections(d):
        lines.append(h)
        lines += [f"• {r}" for r in rows]
        lines.append("")
    lines.append("Уровни доказанности: T0 — заявлено кандидатом, T1 — подтверждено тестом/заданиями, "
                 "T2 — подтверждено реестром ФСП.")
    return "\n".join(lines)


def _link_html(row: str) -> str:
    """Строка «Название: https://…» → ссылка (упрощённый HTML, который принимают Talantix TMS и «Поток»)."""
    m = re.match(r"^(.*?): (https?://\S+)$", row)
    if m:
        return f'{html.escape(m.group(1))}: <a href="{html.escape(m.group(2))}">{html.escape(m.group(2))}</a>'
    return html.escape(row)


def as_html(d: dict) -> str:
    parts = []
    for i, (h, rows) in enumerate(sections(d)):
        parts.append(f"<p><strong>{html.escape(h)}</strong></p>")
        parts.append("<ul>" + "".join(f"<li>{_link_html(r)}</li>" for r in rows) + "</ul>")
    parts.append("<p>Уровни доказанности: T0 — заявлено кандидатом, T1 — подтверждено тестом/заданиями, "
                 "T2 — подтверждено реестром ФСП.</p>")
    return "".join(parts)


def comment_text(d: dict, *, update: bool = False) -> str:
    """Короткий комментарий в карточку кандидата на вакансии ATS."""
    lines = [("Профиль обновлён на платформе «Встречный». " if update else "") + offer_text(d),
             f"Категория: {d['category_title'] or 'не присвоена'}."]
    tl = test_line(d)
    if tl:
        lines.append(f"[T1] {tl}.")
    if d["skills"]:
        lines.append("[T1] Подтверждённые навыки: " + ", ".join(key_skills(d)[:8]) + ".")
    if d["fsp"]["achievements"]:
        lines.append("[T2] ФСП: " + "; ".join(d["fsp"]["achievements"][:3]) + ".")
    if d["pdf_url"]:
        lines.append(f"PDF-профиль: {d['pdf_url']}")
    return "\n".join(lines)
