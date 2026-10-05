"""Интеграции (день 3Б): ФНС ЕГРЮЛ и индекс доверия работодателя, ФСП ID (Keycloak OIDC), ATS (Хантфлоу,
вебхук, экспорт JSON, тестовая заглушка), вакансии и отклики, Web Push, опрос SUS.

Пакеты независимы от основных модулей: подключаются одной функцией ``include_routers(app)``, а в основные
сценарии встроены только через фоновые хуки ``app.integrations.events``.
"""
from fastapi import FastAPI


def include_routers(app: FastAPI) -> None:
    from app.integrations.ats.router import export_router as ats_export_router
    from app.integrations.ats.router import router as ats_router
    from app.integrations.ats.stub_router import router as ats_stub_router
    from app.integrations.egrul.router import router as trust_router
    from app.integrations.fsp_id.router import router as fsp_id_router
    from app.integrations.push.router import router as push_router
    from app.integrations.sus.router import admin_router as sus_admin_router
    from app.integrations.sus.router import router as sus_router
    from app.integrations.vacancies.router import candidate_router as vac_candidate_router
    from app.integrations.vacancies.router import employer_router as vac_employer_router
    from app.integrations.vacancies.router import public_router as vac_public_router

    for r in (trust_router, fsp_id_router, ats_router, ats_export_router, ats_stub_router, vac_employer_router,
              vac_public_router, vac_candidate_router, push_router, sus_router, sus_admin_router):
        app.include_router(r)


TAGS = [
    {"name": "employer-trust", "description": "Проверка работодателя в ЕГРЮЛ (ФНС) и индекс доверия"},
    {"name": "fsp-id", "description": "Вход и связка через ФСП ID (демо, Keycloak, OIDC + PKCE)"},
    {"name": "ats", "description": "Передача кандидатов в ATS: Хантфлоу API v2, вебхук с HMAC, экспорт JSON"},
    {"name": "ats-stub", "description": "Тестовая ATS-заглушка (Хантфлоу-совместимая) для демо"},
    {"name": "vacancies", "description": "Вакансии и отклики кандидатов"},
    {"name": "push", "description": "Web Push (VAPID) для PWA"},
    {"name": "sus", "description": "Опрос юзабилити SUS и агрегаты для /validation"},
]
