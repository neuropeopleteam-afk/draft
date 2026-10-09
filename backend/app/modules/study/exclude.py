"""Кого не считаем: автотесты, служебные и демонстрационные учётные записи, чужие роли.

Статистика прохождения нужна про людей на стенде. Свой трафик команды (Playwright, e2e, нагрузка, сиды, служебные
учётки) в неё не входит: он отсекается и в браузере (navigator.webdriver), и здесь, по заголовку User-Agent и по
учётной записи. Оставшийся ручной прогон команды убирает команда ``reset-study``.
"""
from __future__ import annotations

import re

from app.core.config import get_settings
from app.core.enums import UserRole
from app.modules.auth.models import User
from app.modules.jury import scope

AUTOMATION_UA = re.compile(
    r"headless|playwright|puppeteer|selenium|webdriver|phantomjs|cypress|lighthouse|python-|curl/|wget|httpx|aiohttp|"
    r"okhttp|go-http|node-fetch|axios|undici|k6/|locust|postman|insomnia|testclient|\bbot\b|spider|crawl", re.I)
# почта для проверок: e2e-…, test…, qa…, smoke…, playwright…, а также адреса документации (example.*, *.test, *.invalid)
TEST_LOCAL = re.compile(r"(^|[._+\-])(e2e|test|tests|testing|qa|smoke|autotest|playwright|selenium|load|loadtest|probe|"
                        r"bot|robot)([._+\-0-9]|$)", re.I)
TEST_DOMAIN = re.compile(r"(^|\.)(example\.(com|org|net)|test|invalid|localhost|local|example)$", re.I)
# персоны жюри, у которых есть путь кандидата или работодателя; эксперт и ФСП — другие роли
JURY_PERSONAS = {"candidate", "candidate_nofsp", "candidate_junior", "candidate_new", "employer"}

REASONS = {
    "disabled": "Сбор статистики выключен на этом сервере",
    "automation": "Автотест или служебный клиент",
    "role": "Роль не участвует в статистике",
    "shared_demo": "Общее демо жюри одно на многих людей",
    "service": "Служебная или демонстрационная учётная запись",
    "test_account": "Учётная запись для проверок",
}


def automation_ua(ua: str | None) -> bool:
    return bool(ua and AUTOMATION_UA.search(ua))


def reason(user: User, *, ua: str | None = None, automation: bool = False) -> str | None:
    """Почему учётная запись или клиент в статистику не входит; None — входит."""
    if not get_settings().study_enabled:
        return "disabled"
    if automation or automation_ua(ua):
        return "automation"
    if user.role not in (UserRole.candidate, UserRole.employer):
        return "role"
    email = (user.email or "").lower()
    local, _, domain = email.partition("@")
    persona, sid = scope.parse(email)
    if email.endswith("@" + scope.DOMAIN):
        if persona is None:
            return "service"  # гости живой демонстрации, служебные учётки на домене жюри
        if not sid:
            return "shared_demo"  # общее демо — один аккаунт на всех экспертов: путь не принадлежит одному человеку
        return None if persona in JURY_PERSONAS else "role"
    if user.is_demo or TEST_DOMAIN.search(domain) or TEST_LOCAL.search(local):
        return "test_account" if not user.is_demo else "service"
    return None
