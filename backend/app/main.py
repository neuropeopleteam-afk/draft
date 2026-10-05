"""Точка входа FastAPI. OpenAPI: /api/docs (Swagger UI), /api/redoc, /api/openapi.json."""
import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.modules.auth.router import router as auth_router
from app.modules.catalog.router import router as catalog_router
from app.modules.profiles.router import router as profiles_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

TAGS = [
    {"name": "auth", "description": "Регистрация, подтверждение почты, вход (JWT)"},
    {"name": "profiles", "description": "Профиль текущего пользователя: кандидат или работодатель"},
    {"name": "catalog", "description": "Справочник направлений, грейдов, категорий и стек-тегов"},
    {"name": "system", "description": "Служебные методы"},
]


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Спецтрек ФСП — API платформы подбора",
        version=s.app_version,
        description=(
            "Платформа подбора ИТ-специалистов с обратной механикой: работодатель находит проверенного "
            "кандидата по категории «направление · грейд» и приглашает с зарплатой.\n\n"
            "Ошибки возвращаются в формате `{\"detail\": {\"code\": \"...\", \"message\": \"...\"}}`."
        ),
        openapi_tags=TAGS,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth_router)
    app.include_router(profiles_router)
    app.include_router(catalog_router)

    class HealthOut(BaseModel):
        status: str
        db: str
        version: str
        dev_mode: bool
        mail_backend: str

    @app.get("/api/health", response_model=HealthOut, tags=["system"], summary="Проверка работоспособности")
    def health(db: Session = Depends(get_db)) -> HealthOut:
        try:
            db.execute(text("SELECT 1"))
            db_state = "ok"
        except Exception:  # noqa: BLE001
            db_state = "error"
        return HealthOut(
            status="ok" if db_state == "ok" else "degraded",
            db=db_state,
            version=s.app_version,
            dev_mode=s.effective_dev_mode,
            mail_backend=s.effective_mail_backend,
        )

    return app


app = create_app()
