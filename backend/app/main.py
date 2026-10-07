"""Точка входа FastAPI. OpenAPI: /api/docs (Swagger UI), /api/redoc, /api/openapi.json.

Swagger UI и ReDoc раздаются с нашего сервера (app/static/apidocs), без внешних CDN.
"""
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.legal import OPERATOR
from app.integrations import TAGS as INTEGRATION_TAGS
from app.integrations import include_routers as include_integration_routers
from app.ideas import TAGS as IDEAS_TAGS
from app.ideas import include_routers as include_ideas_routers
from app.modules.assessment.expert_router import router as expert_router
from app.modules.assessment.router import router as assessment_router
from app.modules.auth.router import router as auth_router
from app.modules.catalog.router import router as catalog_router
from app.modules.experts.router import router as expert_panel_router
from app.modules.invitations.router import candidate_router as candidate_contact_router
from app.modules.invitations.router import employer_router as employer_contact_router
from app.modules.jury.router import make_spare
from app.modules.jury.router import router as jury_router
from app.modules.jury.scope import JuryScopeMiddleware
from app.modules.matching.router import router as employer_router
from app.modules.profiles.candidate_router import legal_router
from app.modules.profiles.candidate_router import router as candidate_router
from app.modules.profiles.router import router as profiles_router
from app.modules.validation.router import router as validation_router

STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

TAGS = [
    {"name": "auth", "description": "Регистрация, подтверждение почты, вход (JWT)"},
    {"name": "profiles", "description": "Профиль текущего пользователя: кандидат или работодатель"},
    {"name": "candidate", "description": "Кандидат: опрос, согласия 152-ФЗ, приватность, ФСП ID, резюме, PDF-профиль"},
    {"name": "assessment", "description": "Тест на грейд и экран «Категория и грейд» (правило 90 дней, демо-режим жюри)"},
    {"name": "candidate-contact", "description": "Кандидат: зонды и приглашения, принятие и отказ"},
    {"name": "employer", "description": "Работодатель: потребности, подборки с версиями, поиск, карточки кандидатов"},
    {"name": "employer-contact", "description": "Работодатель: зонды и приглашения-офферы (вилка обязательна, лимит 30 дней)"},
    {"name": "catalog", "description": "Справочник направлений, грейдов, категорий и стек-тегов"},
    {"name": "legal", "description": "Тексты согласий и реквизиты оператора персональных данных"},
    {"name": "expert-panel", "description": "Экспертная разметка: вход по ссылке, пары, ответы, Ангофф"},
    {"name": "system", "description": "Служебные методы"},
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Запасная песочница жюри — в фоне после старта: первый вход эксперта не ждёт её создания
    if get_settings().jury_spare_sandboxes > 0:
        t = threading.Timer(5.0, make_spare)
        t.daemon = True
        t.start()
    # Обратный канал ATS: опрос этапов кандидатов в «Потоке» (ATS_STAGE_POLL_S; 0 — выключено)
    from app.integrations.ats.stages import start_poller

    start_poller()
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        lifespan=lifespan,
        title="Спецтрек ФСП — API платформы подбора",
        version=s.app_version,
        description=(
            "Платформа подбора ИТ-специалистов с обратной механикой: работодатель находит проверенного "
            "кандидата по категории «направление · грейд» и приглашает с зарплатой.\n\n"
            "Ошибки возвращаются в формате `{\"detail\": {\"code\": \"...\", \"message\": \"...\"}}`."
        ),
        openapi_tags=TAGS + INTEGRATION_TAGS + IDEAS_TAGS,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(JuryScopeMiddleware)  # песочница жюри из токена → видимость кандидатов и ответов
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for r in (auth_router, profiles_router, candidate_router, legal_router, assessment_router,
              candidate_contact_router, employer_router, employer_contact_router, catalog_router,
              expert_router, expert_panel_router, jury_router, validation_router):
        app.include_router(r)
    include_integration_routers(app)
    include_ideas_routers(app)
    app.mount("/api/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/api/docs", include_in_schema=False)
    def swagger() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url="/api/openapi.json", title=f"{s.product_name} — API",
            swagger_js_url="/api/static/apidocs/swagger-ui-bundle.js",
            swagger_css_url="/api/static/apidocs/swagger-ui.css",
            swagger_favicon_url="/api/static/apidocs/favicon-32x32.png",
        )

    @app.get("/api/redoc", include_in_schema=False)
    def redoc() -> HTMLResponse:
        return HTMLResponse(f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>{s.product_name} — API (ReDoc)</title><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="/api/static/apidocs/favicon-32x32.png"><style>body{{margin:0}}</style></head>
<body><redoc spec-url="/api/openapi.json" hide-download-button="false"></redoc>
<script src="/api/static/apidocs/redoc.standalone.js"></script></body></html>""")

    @app.get("/api/meta", tags=["system"], summary="Название продукта, оператор ПДн, статус LLM и движка теста")
    def meta() -> dict:
        from app.modules.assessment.engine import get_engine
        from app.modules.llm.client import status as llm_status

        return {"product_name": s.product_name, "version": s.app_version, "operator": OPERATOR,
                "jury_mode_available": s.jury_mode_available, "demo_sandbox": s.demo_sandbox,
                "llm": llm_status(), "assessment_engine": get_engine().name}

    class HealthOut(BaseModel):
        status: str
        db: str

    @app.get("/api/health", response_model=HealthOut, tags=["system"], summary="Проверка работоспособности",
             description="Только состояние сервиса и БД: режим разработки, почта и версия здесь не раскрываются "
                         "(версия продукта — в /api/meta).")
    def health(db: Session = Depends(get_db)) -> HealthOut:
        try:
            db.execute(text("SELECT 1"))
            db_state = "ok"
        except Exception:  # noqa: BLE001
            db_state = "error"
        return HealthOut(status="ok" if db_state == "ok" else "degraded", db=db_state)

    return app


app = create_app()
