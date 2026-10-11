"""Тарифы работодателя — единственное место, где заданы цены, лимиты и функции (решение владельца 11.10).

Модель «смешанная»: кандидатам всегда бесплатно; работодателю «Старт» бесплатно (несколько приглашений в месяц),
платный «Найм» (больше приглашений, ATS, задания кандидатам, рынок зарплат), «Партнёр ФСП» входит в спонсорский пакет
ФСП и выдаётся федерацией (роль fsp_analyst/admin), не покупается. Отборочные задачи от компаний проводит ФСП на своих
соревнованиях — функция партнёрского пакета.

Цена «Найма» — ДЕМОНСТРАЦИОННАЯ (PRICE_IS_STUB): настоящей оплаты нет, выставляется демо-счёт. Ориентиры рынка —
публичные прайсы на 11.10.2026 (MARKET_REFERENCES); это цены других единиц услуги (вакансия, открытия контактов,
оценка), не оферта и не наша цена. Поменять цену или лимит — только здесь.
"""
from __future__ import annotations

PRICE_IS_STUB = True  # цены не утверждены владельцем: в интерфейсе — «демонстрационная цена, не оферта»
VAT_RATE = 0.22  # НДС 22 % (с 01.01.2026), включён в цену

# Функции тарифов: ключ → подпись в интерфейсе. Проверка — tariffs.service.require_feature / feature_allowed.
FEATURES: dict[str, str] = {
    "ats": "Подключение ATS (Хантфлоу, Talantix, «Поток», вебхук)",
    "assignments": "Задания от работодателя кандидатам с автопроверкой",
    "salary_market": "Рынок зарплат по категории (hh.ru) у вилки приглашения",
    "fsp_selection_tasks": "Отборочные задачи компании на соревнованиях ФСП (проводит ФСП)",
    "partner_badge": "Метка «Партнёр ФСП» в карточке компании и в приглашениях",
}

PLANS: list[dict] = [
    {"id": "start", "title": "Старт", "price_rub_month": 0, "price_note": "Бесплатно",
     "invites_per_month": 3,
     "summary": "Попробовать подбор: потребность текстом, подборка с объяснениями, несколько приглашений в месяц.",
     "features": {"ats": False, "assignments": False, "salary_market": False, "fsp_selection_tasks": False,
                  "partner_badge": False},
     "self_service": True},
    {"id": "hire", "title": "Найм", "price_rub_month": 9_900, "price_note": "в месяц, НДС включён",
     "invites_per_month": 30,
     "summary": "Регулярный найм: больше приглашений, передача в ATS, задания кандидатам, рынок зарплат у вилки.",
     "features": {"ats": True, "assignments": True, "salary_market": True, "fsp_selection_tasks": False,
                  "partner_badge": False},
     "self_service": True},
    {"id": "partner", "title": "Партнёр ФСП", "price_rub_month": None, "price_note": "Входит в спонсорский пакет ФСП",
     "invites_per_month": 100,
     "summary": "Для спонсоров и партнёров федерации: всё из «Найма», отборочные задачи на соревнованиях ФСП, метка "
                "партнёра. Подключает ФСП по договору.",
     "features": {"ats": True, "assignments": True, "salary_market": True, "fsp_selection_tasks": True,
                  "partner_badge": True},
     "self_service": False},
]
PLAN_BY_ID: dict[str, dict] = {p["id"]: p for p in PLANS}
DEFAULT_PLAN = "start"
PAID_PLAN = "hire"

# Компании песочниц жюри (app.modules.jury.seed): тариф по умолчанию, чтобы личные ссылки жюри не упирались в лимит
# «Старта» и показывали все три состояния — свой «Найм», партнёра у второй компании и «Старт» у сомнительной.
JURY_DEFAULTS: dict[str, str] = {
    "Демо жюри: Северный платёж": "hire",
    "Демо жюри: Логистика Онлайн": "partner",
    "Демо жюри: Быстрый заработок": "start",
}

# Ориентиры рынка для страницы «Тарифы» (разведка рынка 11.10): другие единицы услуги, не сравнение «дешевле/дороже».
MARKET_REFERENCES: list[dict] = [
    {"title": "Хабр Карьера — вакансия «Стандарт»", "price": "4 026 ₽ за 30 дней (Москва, СПб, удалённо)",
     "unit": "публикация вакансии, НДС 22 % включён", "url": "https://career.habr.com/price"},
    {"title": "Хабр Карьера — доступ к базе", "price": "42 822 ₽ в месяц",
     "unit": "900 открытий контактов, НДС 22 % включён", "url": "https://career.habr.com/price"},
    {"title": "TestGorilla — Core", "price": "от 215 USD в месяц",
     "unit": "тесты кандидатов, годовая оплата", "url": "https://www.testgorilla.com/pricing/"},
]
MARKET_NOTE = ("Цены других сервисов — публичные прайсы на 11.10.2026 за другие единицы услуги (публикация вакансии, "
               "открытия контактов, тестирование). Это ориентир, не сравнение и не оферта.")


def plan(plan_id: str) -> dict:
    return PLAN_BY_ID.get(plan_id) or PLAN_BY_ID[DEFAULT_PLAN]


def vat_of(amount_rub: int) -> int:
    """НДС, включённый в сумму: amount × 22 / 122, округление до рубля."""
    return int(round(amount_rub * VAT_RATE / (1 + VAT_RATE)))


def public_plans() -> list[dict]:
    return [{**p, "features": dict(p["features"]),
             "feature_list": [{"key": k, "title": t, "included": bool(p["features"].get(k))} for k, t in FEATURES.items()]}
            for p in PLANS]
