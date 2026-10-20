"""Защита от фиктивных вакансий и вакансий-приманок (дополнительный критерий ТЗ — 7 %).

Проверяет вакансии и описания потребностей по шести независимым группам признаков:
1. ``paid_fee`` — требование оплаты от соискателя (платное обучение, взнос за оформление, залог за доступ/оборудование);
2. ``scam_phrases`` — характерные формулировки фиктивных объявлений («быстрый заработок», «лёгкие деньги»,
   «высокий доход с первого дня», «ежедневные выплаты на карту/крипту», «работа с телефона 2 часа в день»);
3. ``salary_bait`` — вилка-приманка: верхняя граница более чем в 2 раза выше рыночного потолка категории,
   либо > 600 000 ₽ при пометке «без опыта», либо чрезмерный разброс вилки (верх / низ > 2,5), либо ниже МРОТ;
4. ``grade_contradiction`` — противоречие уровня и требований (заявлен Senior/Lead, но написано «опыт не важен / без опыта»);
5. ``no_company_identity`` — отсутствие подтверждённого юрлица (нет ИНН/ЕГРЮЛ, низкий индекс доверия < 30,
   обезличенное название из стоп-листа приманок);
6. ``vague_or_off_platform`` — отсутствие конкретных инженерных задач и стека при уводе общения в анонимный бот/мессенджер.

Возвращает структурированный вердикт ``status`` (``verified`` | ``caution`` | ``high_risk``), ``risk_score`` (0..100),
понятный бейдж ``badge_title`` и список сработавших признаков ``flags`` с цитатами.
"""
from __future__ import annotations

import re
from typing import Any

_PAID_FEE_RE = re.compile(
    r"(?:после\s+оплат\w*\s+(?:обучен|стажировк|курс|доступ|материал)|"
    r"платн\w+\s+(?:обучен\w*\s+перед|стажировк|вводн\w+\s+курс)|"
    r"взнос\s+за\s+(?:оформлен|доступ|оборудован|обучен)|"
    r"залог\s+за\s+(?:ноутбук|оборудован|доступ)|"
    r"оплат\w+\s+сертификат\w*\s+для\s+выхода)",
    re.IGNORECASE,
)

_SCAM_PHRASES_RE = re.compile(
    r"(?:быстр\w+\s+заработ\w*|л[её]гк\w+\s+деньг\w*|"
    r"высок\w+\s+доход\s+с\s+первого\s+дня|"
    r"ежедневн\w+\s+выплат\w*\s+на\s+(?:карт|крипт|кошел)|"
    r"выплат\w*\s+в\s+криптовалют\w*\s+без\s+оформлен|"
    r"работ\w+\s+с\s+телефона\s+\d+\s*час|"
    r"доход\s+без\s+потолка\s+без\s+опыта|"
    r"срочный\s+набор\s+без\s+резюме)",
    re.IGNORECASE,
)

_NO_EXP_CLAIM_RE = re.compile(
    r"(?:опыт\s+(?:работы\s+)?не\s+важен|без\s+опыта\s+и\s+знаний|опыт\s+не\s+требуется)",
    re.IGNORECASE,
)

_OFF_PLATFORM_RE = re.compile(
    r"(?:пиш(?:ите|и)\s+сразу\s+в\s+(?:телеграм|telegram|тг|ватсап|whatsapp)|"
    r"отклики\s+здесь\s+не\s+читаем|переходите\s+в\s+(?:наш\s+)?(?:тг[- ]?бот|telegram[- ]?bot))",
    re.IGNORECASE,
)

_BAD_COMPANY_RE = re.compile(
    r"(?:быстрый\s+заработок|лёгкий\s+старт|легкий\s+старт|крипто[- ]?инвест|без\s+названия)",
    re.IGNORECASE,
)

# Ориентиры рыночных потолков (на руки, ₽/мес) по грейдам, если точная категория не передана
DEFAULT_GRADE_HIGH: dict[str, int] = {
    "intern": 90_000,
    "junior": 150_000,
    "middle": 300_000,
    "senior": 480_000,
    "lead": 600_000,
    "principal": 750_000,
}

DEFAULT_GRADE_LOW: dict[str, int] = {
    "intern": 30_000,
    "junior": 60_000,
    "middle": 120_000,
    "senior": 220_000,
    "lead": 280_000,
    "principal": 350_000,
}


def _quote(text: str, m: re.Match | None) -> str | None:
    if not m:
        return None
    return text[m.start() : m.end()].strip()[:140]


def assess_vacancy(
    *,
    title: str | None = None,
    text: str | None = None,
    grade: str | None = None,
    salary_from: int | None = None,
    salary_to: int | None = None,
    salary_net: bool | None = None,
    stack_count: int | None = None,
    market_from: int | None = None,
    market_to: int | None = None,
    company_name: str | None = None,
    has_inn: bool | None = None,
    trust_score: int | None = None,
    trust_level: str | None = None,
) -> dict[str, Any]:
    """Оценивает вакансию или потребность на признаки фиктивности и приманки."""
    full_text = "\n".join(x for x in (title, text) if x).strip()
    flags: list[dict[str, Any]] = []
    risk = 0

    # 1. Платное обучение / взнос от кандидата
    if m := _PAID_FEE_RE.search(full_text):
        q = _quote(full_text, m)
        flags.append({
            "code": "paid_fee",
            "severity": "high",
            "title": "Требование оплаты от кандидата",
            "text": f"В тексте упоминается платное обучение или взнос перед оформлением («{q}»).",
            "quote": q,
        })
        risk += 55

    # 2. Фразы «быстрого заработка» и нереалистичных обещаний
    if m := _SCAM_PHRASES_RE.search(full_text):
        q = _quote(full_text, m)
        flags.append({
            "code": "scam_phrases",
            "severity": "high",
            "title": "Признаки вакансии-приманки в тексте",
            "text": f"Обнаружена характерная формулировка-приманка («{q}»).",
            "quote": q,
        })
        risk += 40

    # 3. Проверка зарплатной вилки относительно рынка категории
    hi_ref = market_to or (DEFAULT_GRADE_HIGH.get(grade or "") if grade else 450_000)
    lo_ref = market_from or (DEFAULT_GRADE_LOW.get(grade or "") if grade else 60_000)
    s_hi = salary_to or salary_from
    s_lo = salary_from or salary_to
    if s_hi:
        net_factor = 1.0 if salary_net else 0.87
        hi_net = round(s_hi * net_factor)
        lo_net = round((s_lo or s_hi) * net_factor)
        if hi_ref and hi_net > 2.0 * hi_ref:
            flags.append({
                "code": "salary_bait",
                "severity": "high",
                "title": "Вилка более чем вдвое выше рынка",
                "text": (
                    f"Верхняя граница вилки ({s_hi:,} ₽)".replace(",", " ")
                    + f" более чем в 2 раза превышает рыночный потолок роли ({hi_ref:,} ₽ на руки) — характерно для вакансий-приманок.".replace(",", " ")
                ),
            })
            risk += 40
        elif lo_ref and lo_net < 0.45 * lo_ref:
            flags.append({
                "code": "salary_below_market",
                "severity": "medium",
                "title": "Вилка заметно ниже рынка роли",
                "text": (
                    f"Нижняя граница ({s_lo:,} ₽)".replace(",", " ")
                    + f" более чем вдвое ниже рыночного ориентира роли ({lo_ref:,} ₽ на руки).".replace(",", " ")
                ),
            })
            risk += 20
        if s_lo and s_hi and s_lo > 0 and (s_hi / s_lo) > 2.5:
            flags.append({
                "code": "salary_wide_spread",
                "severity": "medium",
                "title": "Чрезмерно широкая зарплатная вилка",
                "text": f"Разброс между нижней и верхней границей превышает 2,5 раза ({s_lo:,} – {s_hi:,} ₽).".replace(",", " "),
            })
            risk += 18

    # 4. Противоречие уровня (Senior/Lead + «без опыта / опыт не важен»)
    no_exp = _NO_EXP_CLAIM_RE.search(full_text)
    if no_exp and (
        (grade in ("senior", "lead", "principal"))
        or re.search(r"\b(?:senior|сеньор|lead|тимлид|principal)\b", title or "", re.I)
        or (s_hi and s_hi >= 500_000)
    ):
        q = _quote(full_text, no_exp)
        flags.append({
            "code": "grade_contradiction",
            "severity": "high",
            "title": "Противоречие между уровнем/доходом и опытом",
            "text": f"Заявлен высокий грейд или доход при условии «{q}».",
            "quote": q,
        })
        risk += 35

    # 5. Проверка компании / реквизитов ЕГРЮЛ
    if company_name and _BAD_COMPANY_RE.search(company_name):
        flags.append({
            "code": "no_company_identity",
            "severity": "high",
            "title": "Подозрительное название работодателя",
            "text": f"Компания «{company_name}» не подтверждена в реестре ЕГРЮЛ или содержит маркеры приманки.",
        })
        risk += 35
    elif trust_level == "low" or (trust_score is not None and trust_score < 35):
        flags.append({
            "code": "low_company_trust",
            "severity": "high",
            "title": "Низкий индекс доверия компании",
            "text": "Компания не прошла проверку по реестру ФНС / корпоративному домену или имеет жалобы соискателей.",
        })
        risk += 35
    elif has_inn is False:
        flags.append({
            "code": "missing_inn",
            "severity": "medium",
            "title": "Реквизиты юрлица не указаны",
            "text": "В профиле работодателя пока не указан ИНН для автоматической сверки с ЕГРЮЛ.",
        })
        risk += 15

    # 6. Увод в сторонние мессенджеры или отсутствие стека
    if m := _OFF_PLATFORM_RE.search(full_text):
        q = _quote(full_text, m)
        flags.append({
            "code": "off_platform_lure",
            "severity": "medium",
            "title": "Увод общения в сторонний мессенджер до отклика",
            "text": f"Призыв перейти во внешний канал до официального приглашения («{q}»).",
            "quote": q,
        })
        risk += 25

    if stack_count == 0 and len(full_text) > 30:
        flags.append({
            "code": "no_tech_stack",
            "severity": "low",
            "title": "Не указан технический стек",
            "text": "В описании не найдено конкретных технологий из инженерного справочника — уточните задачи перед откликом.",
        })
        risk += 10

    risk_score = min(100, risk)
    high_count = sum(1 for f in flags if f["severity"] == "high")

    if risk_score >= 45 or high_count >= 1:
        status = "high_risk"
        badge_title = "Риск фиктивной вакансии"
        summary = flags[0]["text"] if flags else "Обнаружены признаки вакансии-приманки."
    elif risk_score >= 15 or flags:
        status = "caution"
        badge_title = "Требует внимания"
        summary = flags[0]["text"]
    else:
        status = "verified"
        badge_title = "Проверенный работодатель и вилка"
        summary = "Зарплатная вилка соответствует рынку категории, признаков вакансии-приманки в тексте не обнаружено."

    return {
        "status": status,
        "badge_title": badge_title,
        "risk_score": risk_score,
        "is_suspicious": status != "verified",
        "flags": flags,
        "summary": summary,
    }


def assess_need_dict(req: dict[str, Any], text: str, title: str | None = None) -> dict[str, Any]:
    """Проверка разобранной потребности работодателя на признаки недобросовестной вакансии."""
    stack_n = len(req.get("stack_required") or []) + len(req.get("stack_desired") or [])
    return assess_vacancy(
        title=title,
        text=text,
        grade=req.get("grade"),
        salary_from=req.get("salary_from"),
        salary_to=req.get("salary_to"),
        salary_net=req.get("salary_net"),
        stack_count=stack_n,
    )
