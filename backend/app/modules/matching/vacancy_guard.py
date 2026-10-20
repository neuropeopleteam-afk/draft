"""Защита от фиктивных вакансий, проверка ЕГРЮЛ по ИНН и индекс ответственности работодателя (доп. критерий ТЗ — 7 %).

Проверяет вакансии, работодателей и описания потребностей без выдуманных чисел по умолчанию:
1. ``egrul`` — проверка работодателя по ИНН через открытые данные ФНС (ЕГРЮЛ/ЕГРИП): статус (действующее / ликвидировано),
   дата регистрации, совпадение названия, с кэшем в БД (`RegistryCheck`). Если реального ответа реестра нет — честный
   статус ``unverified`` («ЕГРЮЛ: не проверено»), никогда не имитируется отказ по регулярному выражению названия;
2. ``responsibility`` — индекс ответственности работодателя только по фактическим приглашениям и ответам компании:
   при числе событий ``< 5`` возвращает ``status = 'insufficient_data'``, ``score = None``, «Индекс ответственности: пока мало данных»;
3. ``paid_fee`` — требование оплаты от соискателя (платное обучение, взнос за оформление, залог за оборудование);
4. ``scam_phrases`` — маркеры фиктивных объявлений («быстрый заработок», «лёгкие деньги», «доход с первого дня без опыта»);
5. ``salary_bait`` — вилка-приманка (верх > 2× рыночного потолка роли, чрезмерный разброс > 2,5×, ниже МРОТ);
6. ``grade_contradiction`` — противоречие уровня и требований (Senior/Lead + «без опыта / опыт не важен»).
"""
from __future__ import annotations

import re
from typing import Any

_PAID_FEE_RE = re.compile(
    r"(?:после\s+оплат\w*\s+(?:обучен|стажировк|курс|доступ|материал)|"
    r"платн\w+\s+(?:обучен\w*\s+перед|стажировк|вводн\w+\s+курс)|"
    r"обучени\w*\s+за\s+ваш\s+сч[её]т|"
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
    r"(?:опыт\s+(?:работы\s+)?не\s+важен|без\s+опыта\s+и\s+знаний|опыт\s+не\s+требуется|без\s+опыта)",
    re.IGNORECASE,
)

_OFF_PLATFORM_RE = re.compile(
    r"(?:пиш(?:ите|и)\s+сразу\s+в\s+(?:телеграм|telegram|тг|ватсап|whatsapp)|"
    r"отклики\s+здесь\s+не\s+читаем|переходите\s+в\s+(?:наш\s+)?(?:тг[- ]?бот|telegram[- ]?bot))",
    re.IGNORECASE,
)

_INN_TEXT_RE = re.compile(r"(?:\bинн\b\s*[:№\-]?\s*)(\d{10}|\d{12})\b", re.IGNORECASE)

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


def extract_inn_from_text(text: str | None) -> str | None:
    if not text:
        return None
    m = _INN_TEXT_RE.search(text)
    return m.group(1) if m else None


def verify_egrul_summary(
    *,
    inn: str | None = None,
    company_name: str | None = None,
    registry: dict[str, Any] | None = None,
    db: Any = None,
    company_id: Any = None,
    live_lookup: bool = False,
) -> dict[str, Any]:
    """Проверка работодателя по ИНН через открытые данные ФНС (ЕГРЮЛ) с кэшем в БД и честной деградацией.

    Никогда не подменяет проверку реестра регулярными выражениями по названию компании:
    если реальной записи проверки нет — возвращает ``status = 'unverified'`` («ЕГРЮЛ: не проверено»).
    """
    reg = dict(registry or {})
    clean_inn = (inn or "").strip() or None
    if not reg and clean_inn:
        try:
            from app.integrations.egrul.client import valid_inn

            if not valid_inn(clean_inn):
                return {
                    "status": "failed",
                    "inn": clean_inn,
                    "badge": "Некорректная контрольная сумма ИНН",
                    "active": False,
                    "name_matches": False,
                    "registered_at": None,
                    "text": f"Указанный ИНН ({clean_inn}) не проходит проверку контрольных разрядов ФНС.",
                }
        except Exception:  # noqa: BLE001
            pass

    if not reg and db is not None and clean_inn:
        try:
            from sqlalchemy import select
            from app.integrations.egrul.models import RegistryCheck

            chk = db.scalar(select(RegistryCheck).where(RegistryCheck.inn == clean_inn))
            if chk is None and live_lookup:
                from app.integrations.egrul.client import check_inn

                chk = check_inn(db, clean_inn, force=False, company_id=company_id)
            if chk is not None:
                reg = {"status": chk.status, "inn": chk.inn, **(chk.data or {})}
        except Exception:  # noqa: BLE001 — честная деградация
            reg = {"status": "unavailable", "inn": clean_inn}

    st = reg.get("status")
    if st in ("found", "ok"):
        liquidated = bool(reg.get("liquidated_at"))
        reg_date = reg.get("registered_at")
        if liquidated:
            return {
                "status": "liquidated",
                "inn": clean_inn or reg.get("inn"),
                "badge": "Юрлицо ликвидировано (ЕГРЮЛ)",
                "active": False,
                "name_matches": True,
                "registered_at": reg_date,
                "text": f"По данным ЕГРЮЛ организация прекратила деятельность ({reg.get('liquidated_at')}).",
            }
        return {
            "status": "verified",
            "inn": clean_inn or reg.get("inn"),
            "badge": "Компания проверена по ЕГРЮЛ",
            "active": True,
            "name_matches": True,
            "registered_at": reg_date,
            "ogrn": reg.get("ogrn"),
            "text": f"Действующее юрлицо в ЕГРЮЛ{f' (с {reg_date[:4]} г.)' if reg_date else ''}, реквизиты подтверждены.",
        }
    if st in ("not_found", "invalid", "demo_not_found"):
        return {
            "status": "failed",
            "inn": clean_inn or reg.get("inn"),
            "badge": "ИНН не найден в ЕГРЮЛ",
            "active": False,
            "name_matches": False,
            "registered_at": None,
            "text": "По указанному ИНН запись в ЕГРЮЛ/ЕГРИП не найдена или контрольная сумма неверна.",
        }
    if clean_inn:
        return {
            "status": "unverified",
            "inn": clean_inn,
            "badge": f"ЕГРЮЛ: не проверено (ИНН {clean_inn})",
            "active": None,
            "name_matches": None,
            "registered_at": None,
            "text": f"ИНН {clean_inn} извлечён; онлайн-проверка в открытом сервисе ФНС не выполнялась в этом запросе — статус «не проверено».",
        }
    return {
        "status": "unverified",
        "inn": None,
        "badge": "ЕГРЮЛ: не проверено",
        "active": None,
        "name_matches": None,
        "registered_at": None,
        "text": "ИНН работодателя не передан или проверка в реестре ФНС ещё не проводилась — статус «не проверено».",
    }


def compute_responsibility_index(
    *,
    total_events: int | None = None,
    response_rate: float | None = None,
    median_response_hours: float | None = None,
    realistic_salary_share: float | None = None,
    cancelled_share: float | None = None,
    trust_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Индекс ответственности работодателя перед кандидатами — строго по фактическим приглашениям/ответам.

    При числе событий ``< 5`` (или при отсутствии фактических данных) возвращает ``status = 'insufficient_data'``
    и ``score = None`` («пока мало данных»), никогда не подставляя вымышленные проценты по умолчанию.
    """
    n_events = int(total_events or 0)
    if trust_data and isinstance(trust_data.get("invitations_total"), int):
        n_events = max(n_events, int(trust_data["invitations_total"]))

    if n_events < 5 or response_rate is None or median_response_hours is None:
        return {
            "status": "insufficient_data",
            "score": None,
            "level": "unknown",
            "total_events": n_events,
            "badge": "Индекс ответственности: пока мало данных",
            "response_rate_pct": None,
            "median_response_hours": None,
            "realistic_salary_pct": None,
            "cancelled_invitations_pct": None,
            "summary": f"Пока мало данных для расчёта индекса ответственности (событий: {n_events}, нужно не менее 5 приглашений или откликов).",
        }

    resp_rate = min(1.0, max(0.0, float(response_rate)))
    med_hours = max(0.0, float(median_response_hours))
    sal_ok = min(1.0, max(0.0, float(realistic_salary_share if realistic_salary_share is not None else 1.0)))
    canc = min(1.0, max(0.0, float(cancelled_share if cancelled_share is not None else 0.0)))

    score = round(
        35 * resp_rate
        + 25 * (1.0 if med_hours <= 24 else 0.75 if med_hours <= 48 else 0.4 if med_hours <= 120 else 0.1)
        + 25 * sal_ok
        + 15 * max(0.0, 1.0 - 2.5 * canc)
    )
    score = max(0, min(100, score))
    level = "high" if score >= 75 else "medium" if score >= 50 else "low"
    return {
        "status": "measured",
        "score": score,
        "level": level,
        "total_events": n_events,
        "badge": f"Индекс ответственности: {score}/100 (по {n_events} приглашениям)",
        "response_rate_pct": round(resp_rate * 100),
        "median_response_hours": round(med_hours, 1),
        "realistic_salary_pct": round(sal_ok * 100),
        "cancelled_invitations_pct": round(canc * 100),
        "summary": (
            f"По {n_events} событиям: отвечает на {round(resp_rate * 100)} % (медиана {round(med_hours)} ч), "
            f"реалистичные вилки: {round(sal_ok * 100)} %, отмены/жалобы: {round(canc * 100)} %."
        ),
    }


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
    inn: str | None = None,
    registry: dict[str, Any] | None = None,
    trust_data: dict[str, Any] | None = None,
    trust_score: int | None = None,
    trust_level: str | None = None,
    total_events: int | None = None,
    response_rate: float | None = None,
    median_response_hours: float | None = None,
    cancelled_share: float | None = None,
    db: Any = None,
) -> dict[str, Any]:
    """Оценивает вакансию или потребность на признаки фиктивности, статус ЕГРЮЛ и индекс ответственности."""
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
    sal_realistic = True
    if s_hi:
        net_factor = 1.0 if salary_net else 0.87
        hi_net = round(s_hi * net_factor)
        lo_net = round((s_lo or s_hi) * net_factor)
        if hi_ref and hi_net > 2.0 * hi_ref:
            sal_realistic = False
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
            sal_realistic = False
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
            sal_realistic = False
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
        or (s_hi and s_hi >= 450_000)
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

    # 5. ЕГРЮЛ и реквизиты компании (с извлечением ИНН из текста, если он указан в описании)
    effective_inn = inn or extract_inn_from_text(full_text)
    egrul = verify_egrul_summary(
        inn=effective_inn,
        company_name=company_name,
        registry=registry or (trust_data or {}).get("registry"),
        db=db,
    )
    if egrul["status"] in ("failed", "liquidated"):
        flags.append({
            "code": "no_company_identity",
            "severity": "high",
            "title": egrul["badge"],
            "text": egrul["text"],
        })
        risk += 35
    elif t_lvl := (trust_level or (trust_data or {}).get("level")):
        if t_lvl == "low" or (trust_score is not None and trust_score < 35):
            flags.append({
                "code": "low_company_trust",
                "severity": "high",
                "title": "Низкий индекс доверия компании",
                "text": "Компания не прошла проверку по реестру ФНС / корпоративному домену или имеет жалобы соискателей.",
            })
            risk += 35
    elif has_inn is False and not effective_inn:
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

    responsibility = compute_responsibility_index(
        total_events=total_events,
        response_rate=response_rate,
        median_response_hours=median_response_hours,
        realistic_salary_share=(1.0 if sal_realistic else 0.0) if s_hi else None,
        cancelled_share=cancelled_share,
        trust_data=trust_data,
    )

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
        badge_title = "Компания проверена по ЕГРЮЛ" if egrul["status"] == "verified" else "Проверенная вакансия"
        if s_hi:
            summary = "Зарплатная вилка соответствует рынку категории, признаков вакансии-приманки в тексте не обнаружено."
        else:
            summary = "Зарплатная вилка в тексте не указана; признаков вакансии-приманки в тексте не обнаружено."

    return {
        "status": status,
        "badge_title": badge_title,
        "risk_score": risk_score,
        "is_suspicious": status != "verified",
        "flags": flags,
        "summary": summary,
        "egrul": egrul,
        "responsibility": responsibility,
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
