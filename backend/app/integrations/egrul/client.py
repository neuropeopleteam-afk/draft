"""Проверка работодателя по ИНН через официальный сервис ФНС «Предоставление сведений из ЕГРЮЛ/ЕГРИП».

Протокол сервиса egrul.nalog.ru (тот же, что использует его веб-страница):
1. ``POST https://egrul.nalog.ru/`` с формой ``query=<ИНН>`` → ``{"t": "<токен>", "captchaRequired": false}``;
2. ``GET https://egrul.nalog.ru/search-result/<t>`` → ``{"rows": [{"n": полное имя, "c": краткое, "i": ИНН,
   "o": ОГРН, "p": КПП, "r": дата регистрации, "e": дата прекращения, "g": руководитель, "rn": регион, "k": ul|fl}]}``.
   Пока результат готовится, сервис отвечает ``{"status": "wait"}`` — повторяем запрос.

Ответы кэшируются на 7 дней (таблица company_registry_checks). Капча или сбой сервиса — мягкая деградация:
статус «не удалось проверить», повтор не раньше чем через 10 минут; остальные признаки индекса доверия работают.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
import re
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import as_aware, utcnow
from app.integrations.egrul.models import RegistryCheck
from app.integrations.settings import get_isettings

log = logging.getLogger(__name__)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
RETRY_AFTER_FAILURE = timedelta(minutes=10)


def valid_inn(inn: str) -> bool:
    """Контрольные цифры ИНН (10 цифр — организация, 12 — физлицо/ИП)."""
    if not re.fullmatch(r"\d{10}|\d{12}", inn or ""):
        return False
    d = [int(x) for x in inn]

    def ctrl(coefs: list[int], n: int) -> int:
        return sum(c * v for c, v in zip(coefs, d[:n], strict=False)) % 11 % 10

    if len(d) == 10:
        return ctrl([2, 4, 10, 3, 5, 9, 4, 6, 8], 9) == d[9]
    return (ctrl([7, 2, 4, 10, 3, 5, 9, 4, 6, 8], 10) == d[10]
            and ctrl([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8], 11) == d[11])


def _date(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%d.%m.%Y").date().isoformat()
    except ValueError:
        return None


def parse_row(row: dict) -> dict:
    """Строка ответа ЕГРЮЛ → нормализованные сведения (без лишних ПДн: только руководитель — публичные сведения)."""
    director_role, director_name = None, None
    g = (row.get("g") or "").strip()
    if g:
        if ":" in g:
            director_role, director_name = (x.strip() for x in g.split(":", 1))
        else:
            director_name = g
    return {
        "name": row.get("n"), "short_name": row.get("c") or row.get("n"), "inn": row.get("i"),
        "ogrn": row.get("o"), "kpp": row.get("p"), "registered_at": _date(row.get("r")),
        "liquidated_at": _date(row.get("e")), "director": director_name,
        "director_role": director_role.capitalize() if director_role else None,
        "region": row.get("rn"), "kind": row.get("k"),  # ul — юрлицо, fl — ИП
    }


def fetch(inn: str) -> tuple[str, dict, str | None]:
    """Запрос к egrul.nalog.ru. Возвращает (status, data, error); исключений наружу не бросает."""
    s = get_isettings()
    if s.egrul_disabled:
        return "error", {}, "Проверка ФНС отключена настройкой"
    base = s.egrul_base_url.rstrip("/")
    headers = {"User-Agent": UA, "X-Requested-With": "XMLHttpRequest", "Referer": base + "/",
               "Accept": "application/json, text/javascript, */*; q=0.01"}
    try:
        with httpx.Client(timeout=s.egrul_timeout_s, headers=headers, follow_redirects=True) as c:
            r = c.post(base + "/", data={"vyp3CaptchaToken": "", "page": "", "query": inn, "region": "",
                                         "PreventChromeAutocomplete": ""})
            if r.status_code != 200:
                return "error", {}, f"ФНС ответила {r.status_code}"
            j = r.json()
            if j.get("captchaRequired"):
                return "captcha", {}, "ФНС запросила капчу"
            t = j.get("t")
            if not t:
                return "error", {}, "ФНС не вернула токен запроса"
            for attempt in range(5):
                ms = int(time.time() * 1000)
                r2 = c.get(f"{base}/search-result/{t}", params={"r": ms, "_": ms})
                if r2.status_code != 200:
                    return "error", {}, f"ФНС ответила {r2.status_code}"
                j2 = r2.json()
                if j2.get("status") == "wait":
                    time.sleep(0.4 + 0.3 * attempt)
                    continue
                rows = j2.get("rows") or []
                row = next((x for x in rows if x.get("i") == inn), None)
                if row is None:
                    return "not_found", {}, None
                return "found", parse_row(row), None
            return "error", {}, "ФНС не успела подготовить ответ"
    except (httpx.HTTPError, ValueError) as e:
        log.warning("egrul: %s", type(e).__name__)
        return "error", {}, f"Сервис ФНС недоступен ({type(e).__name__})"


def is_fresh(chk: RegistryCheck) -> bool:
    return as_aware(chk.expires_at) > utcnow()


def check_inn(db: Session, inn: str, *, force: bool = False, company_id=None) -> RegistryCheck:
    """Сведения ЕГРЮЛ по ИНН с кэшем на 7 дней (успешные ответы) / 10 минут (капча, сбой)."""
    inn = (inn or "").strip()
    chk = db.scalar(select(RegistryCheck).where(RegistryCheck.inn == inn))
    if chk is not None and is_fresh(chk) and not (force and chk.status in ("captcha", "error")):
        return chk
    if not valid_inn(inn):
        status, data, error = "invalid", {}, "Неверная контрольная сумма ИНН"
    else:
        status, data, error = fetch(inn)
    if chk is not None and status in ("captcha", "error") and chk.status == "found":
        # Сервис временно недоступен, но есть прежние сведения — оставляем их, повторим позже
        chk.error = error
        chk.expires_at = utcnow() + RETRY_AFTER_FAILURE
        db.commit()
        return chk
    ttl = timedelta(days=get_isettings().egrul_cache_days) if status in ("found", "not_found", "invalid") \
        else RETRY_AFTER_FAILURE
    if chk is None:
        chk = RegistryCheck(inn=inn)
        db.add(chk)
    chk.status, chk.data, chk.error = status, data, error
    chk.checked_at = utcnow()
    chk.expires_at = utcnow() + ttl
    chk.requested_by_company = company_id
    db.commit()
    return chk


def age_years(registered_at: str | None, today: date | None = None) -> float | None:
    if not registered_at:
        return None
    d = date.fromisoformat(registered_at)
    return round(((today or date.today()) - d).days / 365.25, 1)
