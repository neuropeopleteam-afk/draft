"""Стандартизированный PDF-профиль кандидата (reportlab, BSD).

Одна структура для всех: категория и результат теста (T1), паспорт ФСП (T2), затем самоописание (T0)
с явной пометкой уровня доказанности. Контакты включаются только в версию для самого кандидата и для
работодателя, чьё приглашение кандидат принял.
"""
from __future__ import annotations

from datetime import date
import io
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import get_settings

NIGHT = colors.HexColor("#310F53")
BRAND = colors.HexColor("#FF0053")
LAVENDER = colors.HexColor("#8A83D1")
BLUSH = colors.HexColor("#FFD6E4")
INK = colors.HexColor("#1C1D22")

_FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/local/share/fonts"]
_registered = False


def _fonts() -> tuple[str, str]:
    global _registered
    if not _registered:
        for d in _FONT_DIRS:
            reg, bold = Path(d) / "DejaVuSans.ttf", Path(d) / "DejaVuSans-Bold.ttf"
            if reg.exists() and bold.exists():
                pdfmetrics.registerFont(TTFont("PSans", str(reg)))
                pdfmetrics.registerFont(TTFont("PSans-Bold", str(bold)))
                _registered = True
                break
    return ("PSans", "PSans-Bold") if _registered else ("Helvetica", "Helvetica-Bold")


def _styles():
    reg, bold = _fonts()
    return {
        "h1": ParagraphStyle("h1", fontName=bold, fontSize=18, leading=22, textColor=NIGHT, spaceAfter=2),
        "sub": ParagraphStyle("sub", fontName=reg, fontSize=9.5, leading=13, textColor=LAVENDER),
        "h2": ParagraphStyle("h2", fontName=bold, fontSize=11.5, leading=15, textColor=NIGHT, spaceBefore=10,
                             spaceAfter=4),
        "p": ParagraphStyle("p", fontName=reg, fontSize=9.5, leading=13.5, textColor=INK),
        "small": ParagraphStyle("small", fontName=reg, fontSize=8, leading=11, textColor=colors.HexColor("#6b6b7b")),
        "tag": ParagraphStyle("tag", fontName=bold, fontSize=8, leading=10, textColor=BRAND),
    }


def _esc(s) -> str:
    return (str(s) if s is not None else "—").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rub(v) -> str:
    return f"{int(v):,}".replace(",", " ") + " ₽" if v else "—"


def render_profile(card: dict, *, contacts: dict | None = None, audience: str = "candidate") -> bytes:
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"Профиль кандидата {card.get('ref')}",
                            author=get_settings().product_name)
    el = []
    product = get_settings().product_name
    el.append(Paragraph(f"{_esc(product)} · стандартизированный профиль кандидата", st["sub"]))
    title = contacts.get("full_name") if contacts and contacts.get("full_name") else f"Кандидат {card.get('ref')}"
    el.append(Paragraph(_esc(title), st["h1"]))
    cat = card.get("category") or {}
    el.append(Paragraph(f"Категория: <b>{_esc(cat.get('title') or 'не присвоена')}</b>"
                        + (f" · место в категории {card['rank_in_category']} из {card['category_size']}"
                           if card.get("rank_in_category") else ""), st["p"]))
    el.append(Spacer(1, 4))
    legend = ("Уровни доказанности: <b>T1</b> — подтверждено тестом или зондом на платформе; <b>T2</b> — подтверждено "
              "реестром ФСП; <b>T0</b> — указано самим кандидатом, на категорию и рейтинг не влияет.")
    el.append(Paragraph(legend, st["small"]))

    if contacts:
        el.append(Paragraph("Контакты", st["h2"]))
        rows = [[k, _esc(v)] for k, v in (("Почта", contacts.get("email")), ("Телефон", contacts.get("phone")),
                                          ("Telegram", contacts.get("telegram"))) if v]
        if rows:
            el.append(_table(rows, st))

    el.append(Paragraph("Результат теста · T1", st["h2"]))
    t = card.get("test")
    if t:
        el.append(_table([
            ["Грейд", _esc(card.get("grade_title"))],
            ["Оценка уровня θ", f"{t['theta']:+.2f} ± {t['se']:.2f}" if t.get("theta") is not None else "—"],
            ["Верных ответов", f"{t.get('correct')} из {t.get('answered')}"],
            ["Дата", _esc(t.get("date"))],
        ], st))
        skills = card.get("skills_confirmed") or []
        if skills:
            el.append(Spacer(1, 4))
            el.append(Paragraph("Навыки, подтверждённые заданиями: " + ", ".join(
                f"{_esc(s['title'])} ({int((s.get('score') or 0) * 100)} %)" for s in skills), st["p"]))
    else:
        el.append(Paragraph("Тест ещё не пройден.", st["p"]))
    probes = card.get("probes") or []
    if probes:
        el.append(Paragraph("Задачи от работодателей (зонды) · T1", st["h2"]))
        for pr in probes:
            el.append(Paragraph(f"• {_esc(pr['title'])} — {_esc(pr.get('verdict'))}", st["p"]))

    el.append(Paragraph("Паспорт ФСП · T2", st["h2"]))
    fsp = card.get("fsp") or {}
    if fsp.get("hidden"):
        el.append(Paragraph("Скрыто кандидатом.", st["p"]))
    elif fsp.get("achievements"):
        for a in fsp["achievements"]:
            el.append(Paragraph("• " + _esc(a["text"]), st["p"]))
        if fsp.get("source") == "demo":
            el.append(Paragraph("Источник — демо-реестр хакатона (реальный реестр ФСП подключается через ФСП ID).",
                                st["small"]))
    else:
        el.append(Paragraph("Истории ФСП нет — нейтральное состояние, на рейтинг не влияет отрицательно.", st["p"]))

    el.append(Paragraph("Самоописание · T0", st["h2"]))
    rows = []
    if card.get("stack_declared"):
        rows.append(["Стек", ", ".join(_esc(s["title"]) for s in card["stack_declared"])])
    if card.get("roles"):
        rows.append(["Роли", ", ".join(map(_esc, card["roles"]))])
    if card.get("experience_years") is not None:
        rows.append(["Стаж", f"{card['experience_years']:g} лет"])
    if card.get("soft_skills"):
        rows.append(["Софт-скиллы", ", ".join(map(_esc, card["soft_skills"]))])
    wf = {"office": "Офис", "hybrid": "Гибрид", "remote": "Удалённо", "any": "Любой"}
    if card.get("work_format"):
        rows.append(["Формат работы", wf.get(card["work_format"], card["work_format"])])
    if card.get("city"):
        rows.append(["Город", _esc(card["city"]) + (" · готов к переезду" if card.get("relocation") else "")])
    el.append(_table(rows, st) if rows else Paragraph("Не заполнено.", st["p"]))

    mr = card.get("market_range")
    if mr and audience == "employer":
        el.append(Paragraph("Рынок категории", st["h2"]))
        el.append(Paragraph(f"{_rub(mr['from'])} – {_rub(mr['to'])} (25–75-й перцентиль, медиана {_rub(mr.get('median'))}). "
                            "Источник: калькулятор зарплат Хабр Карьеры.", st["p"]))
    el.append(Spacer(1, 10))
    el.append(Paragraph(f"Сформировано {date.today():%d.%m.%Y} · обезличенный идентификатор {_esc(card.get('ref'))}",
                        st["small"]))
    doc.build(el)
    return buf.getvalue()


def _table(rows, st) -> Table:
    data = [[Paragraph(f"<b>{_esc(a)}</b>", st["p"]), Paragraph(b if isinstance(b, str) else _esc(b), st["p"])]
            for a, b in rows]
    t = Table(data, colWidths=[42 * mm, None])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, BLUSH),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t
