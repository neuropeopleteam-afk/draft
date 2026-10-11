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
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as DBPoolTimeout
from sqlalchemy.orm import Session

from app.core.api_docs import install_openapi
from app.core.config import get_settings
from app.core.db import get_db
from app.core.legal import OPERATOR
from app.integrations import TAGS as INTEGRATION_TAGS
from app.integrations import include_routers as include_integration_routers
from app.ideas import TAGS as IDEAS_TAGS
from app.ideas import include_routers as include_ideas_routers
from app.modules.assignments import feed as assignments_feed
from app.modules.assignments.router import TAGS as ASSIGNMENTS_TAGS
from app.modules.assignments.router import candidate_router as assignments_candidate_router
from app.modules.assignments.router import employer_router as assignments_employer_router
from app.modules.assessment.attempts import employer_router as attempts_employer_router
from app.modules.assessment.evidence_view import candidate_router as evidence_candidate_router
from app.modules.assessment.evidence_view import employer_router as evidence_employer_router
from app.modules.assessment.evidence_view import validation_router as evidence_validation_router
from app.modules.assessment.expert_router import router as expert_router
from app.modules.assessment.router import router as assessment_router
from app.modules.auth.router import router as auth_router
from app.modules.auth.twofa_router import admin_router as twofa_admin_router
from app.modules.auth.twofa_router import router as twofa_router
from app.modules.catalog.router import router as catalog_router
from app.modules.contact import router as contact
from app.modules.experts.router import router as expert_panel_router
from app.modules.hiring import router as hiring  # найм после принятия: собеседование, оффер, исход (Н8)
from app.modules.hh import router as hh_api  # hh.ru: импорт своей вакансии, «Рынок по hh.ru» (Я12, за HH_ENABLED)
from app.modules.interview import router as interview  # устная защита и ИИ-интервью (Я15), флаг INTERVIEW_ENABLED
from app.modules.invitations.router import candidate_router as candidate_contact_router
from app.modules.invitations.router import employer_router as employer_contact_router
from app.modules.jury.router import make_spare
from app.modules.jury.router import router as jury_router
from app.modules.jury.scope import JuryScopeMiddleware
from app.modules.matching.router import router as employer_router
from app.modules.proctor.router import router as proctor_router
from app.modules.mydata.router import router as mydata_router
from app.modules.mutual import router as mutual  # взаимный подбор, отзывы, ссылка руководителю (Н9, Н2, Н3)
from app.modules.profiles.candidate_router import legal_router
from app.modules.profiles.candidate_router import router as candidate_router
from app.modules.profiles.router import router as profiles_router
from app.modules.subs import router as subs_api
from app.modules.subs import runner as subs_runner
from app.modules.study import router as study_api
from app.modules.validation.router import router as validation_router
from app.modules.voice import router as voice  # голосовой ввод потребности (VOICE_NEED_ENABLED)
from app.modules.tariffs import router as tariffs_api  # тарифы работодателя, «Польза для ФСП» (Я29, TARIFFS_ENABLED)
from app.modules.fsp.registry import router as fsp_registry_router
from app.passport.router import TAGS as PASSPORT_TAGS
from app.passport.router import router as passport_router

STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

TAGS = [
    {"name": "auth", "description": "Регистрация, подтверждение почты, вход (JWT), второй фактор (TOTP)"},
    {"name": "profiles", "description": "Профиль текущего пользователя: кандидат или работодатель"},
    {"name": "candidate", "description": "Кандидат: опрос, согласия 152-ФЗ, приватность, ФСП ID, резюме, PDF-профиль"},
    {"name": "assessment", "description": "Тест на грейд и экран «Категория и грейд» (правило 90 дней, демо-режим жюри)"},
    {"name": "proctor", "description": "Камера во время теста по согласию: анализ только в браузере, на сервер — события без кадров; "
                                     "без камеры тест доступен полностью"},
    {"name": "candidate-contact", "description": "Кандидат: зонды и приглашения, принятие и отказ"},
    {"name": "employer", "description": "Работодатель: потребности, подборки с версиями, поиск, карточки кандидатов"},
    {"name": "employer-contact", "description": "Работодатель: зонды и приглашения-офферы (вилка обязательна, лимит 30 дней)"},
    {"name": "catalog", "description": "Справочник направлений, грейдов, категорий и стек-тегов"},
    {"name": "legal", "description": "Тексты согласий и реквизиты оператора персональных данных"},
    {"name": "expert-panel", "description": "Экспертная разметка: вход по ссылке, пары, ответы, Ангофф"},
    {"name": "system", "description": "Служебные методы"},
    {"name": "expert", "description": "Проверка развёрнутых ответов теста по рубрике: очередь, оценка, согласованность экспертов"},
    {"name": "jury", "description": "Жюри: вход в один клик, личная песочница с демо-данными, сброс и удаление песочницы"},
    {"name": "my-data", "description": "«Мои данные»: что хранится о пользователе, выгрузка JSON, удаление, отзыв раскрытых контактов"},
    {"name": "validation", "description": "Публичные метрики качества: валидация теста и подбора, критерии ТЗ, проверка своих данных"},
    {"name": "fsp-registry", "description": "Предложение контракта реестра ФСП и его синтетический мок (не официальный API ФСП)"},
] + subs_api.TAGS


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Запасная песочница жюри — в фоне после старта: первый вход эксперта не ждёт её создания
    if get_settings().jury_spare_sandboxes > 0:
        t = threading.Timer(5.0, make_spare)
        t.daemon = True
        t.start()
    # Лента «Задания для вас»: раз в N дней предложить открытое задание работодателя (И7)
    assignments_feed.start_background(get_settings().assignments_feed_interval_s)
    # Обратный канал ATS: опрос этапов кандидатов в «Потоке» (ATS_STAGE_POLL_S; 0 — выключено)
    from app.integrations.ats.stages import start_poller

    start_poller()
    from app.modules.hiring.reminders import start_background as start_hiring_reminders

    start_hiring_reminders()  # напоминания о собеседованиях (HIRING_REMIND_POLL_S; 0 — выключено)
    # Подписка на потребность и напоминания (И25, Н6): фоновый обход, под арендой в БД
    subs_runner.start_background(get_settings().subs_tick_interval_s)
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
            "Ошибки возвращаются в формате `{\"detail\": {\"code\": \"...\", \"message\": \"...\"}}`; "
            "ошибки проверки полей запроса (422) — в формате FastAPI `{\"detail\": [{\"loc\", \"msg\", \"type\"}]}`.\n\n"
            "Вход: `POST /api/auth/token` (форма) или `POST /api/auth/login` (JSON), далее заголовок "
            "`Authorization: Bearer <JWT>`; кнопка Authorize в Swagger UI принимает ту же пару «почта — пароль». "
            "К каждому методу описаны требуемая роль, коды ошибок и их `detail.code`. Файл спецификации без запуска "
            "сервера — `docs/api/openapi.json` в репозитории (обзор — `docs/API.md`)."
        ),
        openapi_tags=(TAGS + contact.TAGS + hiring.TAGS + INTEGRATION_TAGS + IDEAS_TAGS + ASSIGNMENTS_TAGS + PASSPORT_TAGS
                      + mutual.TAGS + study_api.TAGS + hh_api.TAGS + interview.TAGS + tariffs_api.TAGS),
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    @app.exception_handler(DBPoolTimeout)
    async def db_busy(request, exc):  # noqa: ANN001 — пул соединений исчерпан (docs/LOAD.md, раздел 6)
        """Нет свободного соединения с БД за DB_POOL_TIMEOUT_S: понятный 503 с Retry-After вместо 500 — фронтенд
        повторяет GET через указанное время, Locust и nginx видят перегрузку, а не ошибку кода."""
        logging.getLogger("app.db").warning("Пул соединений с БД исчерпан (%s %s): 503 db_busy", request.method,
                                            request.url.path)
        return JSONResponse(status_code=503, headers={"Retry-After": str(get_settings().db_busy_retry_after_s)},
                            content={"detail": {"code": "db_busy",
                                                "message": "Сервер сейчас перегружен — повторите через несколько секунд"}})

    app.add_middleware(JuryScopeMiddleware)  # песочница жюри из токена → видимость кандидатов и ответов
    app.include_router(fsp_registry_router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for r in (auth_router, twofa_router, twofa_admin_router, profiles_router, candidate_router, legal_router, assessment_router,
              candidate_contact_router, employer_router, employer_contact_router, catalog_router,
              expert_router, expert_panel_router, jury_router, validation_router, proctor_router,
              assignments_employer_router, assignments_candidate_router, passport_router, mydata_router,
              contact.router, contact.candidate_router, contact.employer_router,  # переписка, встречное (И4)
              hiring.router, hiring.candidate_router, hiring.employer_router,  # найм (Н8)
              subs_api.employer_router, subs_api.notify_router, subs_api.jury_router,  # подписка, уведомления (И25)
              attempts_employer_router,  # две попытки теста рядом (И26)
              evidence_candidate_router, evidence_employer_router, evidence_validation_router,  # цитаты
              mutual.employer_router, mutual.candidate_router, mutual.public_router,  # взаимный подбор (Н9, Н2, Н3)
              study_api.router,  # статистика прохождения: живые пользователи (У1)
              hh_api.router, hh_api.validation_router,  # hh.ru (Я12): без HH_ENABLED и токена — 404 hh_disabled
              interview.router, interview.candidate_router, interview.employer_router,  # устная защита (Я15)
              voice.router,  # «Надиктовать» потребность (за флагом VOICE_NEED_ENABLED)
              tariffs_api.public_router, tariffs_api.employer_router, tariffs_api.fsp_router):  # тарифы (Я29)
        app.include_router(r)
    include_integration_routers(app)
    include_ideas_routers(app)
    install_openapi(app)  # ошибки по коду методов и строка «Доступ» в схему (app/core/api_docs.py; поведение API не меняется)
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
                "proctor_camera": get_settings().proctor_camera_enabled,  # на запросе (не замыкание s): флаг переключается без пересоздания app; false — экрана камеры нет
                "llm": llm_status(), "assessment_engine": get_engine().name,
                # сроки правил грейда и приглашений — из настроек, тексты интерфейса берут их отсюда (Ф3)
                "rules": {"grade_change_interval_days": get_settings().grade_change_interval_days,  # на запросе, как proctor_camera
                          "retake_same_grade_days": get_settings().retake_same_grade_days,
                          "invitation_cooldown_days": get_settings().invitation_cooldown_days},
                "interview": interview.svc.meta(),  # устная защита и ИИ-интервью (Я15): {enabled, stub, defense_minutes}
                "interview_enabled": interview.svc.enabled(),  # то же одним флагом — шаг проводника «12 минут» (Я9)
                "hh": hh_api.meta(),  # Я12: кнопка импорта с hh.ru и «Рынок по hh.ru» — только при HH_ENABLED и токене
                "voice_need": voice.meta(),  # кнопка «Надиктовать»: флаг, заглушка, предел секунд, версия согласия
                "tariffs": tariffs_api.svc.meta()}  # Я29: раздел «Тарифы», счётчик приглашений, метка «Партнёр ФСП»

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
