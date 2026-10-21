"""Тесты: временная БД (по умолчанию SQLite-файл), схема создаётся миграциями Alembic.

TEST_DATABASE_URL позволяет прогнать те же тесты на PostgreSQL (make test в контейнере).
"""
import os
from pathlib import Path
import tempfile

_tmp = Path(tempfile.mkdtemp()) / "test.db"
DB_URL = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp}"
os.environ["DATABASE_URL"] = DB_URL
os.environ["DEV_MODE"] = "true"
os.environ["JWT_SECRET"] = "test-secret-not-for-prod-0123456789abcdef"
os.environ["MAIL_BACKEND"] = "dev"
os.environ.setdefault("ASSESSMENT_ENGINE", "stub")  # правила — на быстрой заглушке; банк — tests/test_bank_engine.py
os.environ["LLM_DISABLED"] = "true"
os.environ["ATS_STAGE_POLL_S"] = "0"  # фоновый опрос этапов ATS — вызовами в тестах (stages.sync_due)
os.environ["JURY_SPARE_SANDBOXES"] = "0"  # фоновые песочницы мешали бы очистке БД между тестами; проверка — отдельно
os.environ["HIRING_REMIND_POLL_S"] = "0"  # напоминания о собеседованиях — вызовом reminders.remind_due
os.environ["ASSIGNMENTS_FEED_INTERVAL_S"] = "0"  # фоновая лента заданий — так же; её логика проверяется вызовом run_once
os.environ["VALIDATION_REPORT_TTL_S"] = "0"  # отчёт /validation — без кэша: тесты меняют данные между запросами
os.environ["SUBS_TICK_INTERVAL_S"] = "0"  # фоновый обход подписок (И25) — так же; логика — вызовом runner.tick
# Кэш и счётчики бюджета Насти (concierge_budget: JSON на диске кэша) — свои у каждого процесса pytest. Без этого
# процессы xdist и прошлые прогоны на одной машине делили /tmp/concierge_tts_cache и упирались в суточный лимит:
# 429 avatar_budget вместо ожидаемых 503/200 (test_access_matrix на поде RunPod, 21.10).
os.environ["CONCIERGE_TTS_CACHE_DIR"] = tempfile.mkdtemp(prefix="concierge_cache_")
os.environ.pop("POSTBOX_ACCESS_KEY_ID", None)
os.environ.pop("POSTBOX_SECRET_ACCESS_KEY", None)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import init_engine  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
REFERENCE_TABLES = {"directions", "grades", "categories", "stack_tags", "alembic_version"}


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["skip_logging"] = True
    return cfg


@pytest.fixture(scope="session")
def engine():
    get_settings.cache_clear()
    cfg = alembic_config(DB_URL)
    command.downgrade(cfg, "base") if os.environ.get("TEST_DATABASE_URL") else None
    command.upgrade(cfg, "head")
    eng = init_engine(DB_URL)
    yield eng
    eng.dispose()


def _reset_concierge_budget() -> None:
    import shutil
    import sys

    mod = sys.modules.get("app.modules.interview.concierge_budget")
    if mod is None:  # модуль ещё не загружен — счётчиков нет
        return
    shutil.rmtree(mod._dir(), ignore_errors=True)
    with mod._BURST_LOCK:
        mod._BURST.clear()


@pytest.fixture(autouse=True)
def clean_db(engine):
    from app.core.ratelimit import reset_all

    reset_all()  # лимиты частоты в памяти процесса — у каждого теста свои
    _reset_concierge_budget()  # суточные счётчики Насти — тоже: тест не должен зависеть от того, сколько прошло до него
    yield
    from app.models import metadata

    with engine.begin() as conn:
        for table in reversed(metadata.sorted_tables):
            if table.name not in REFERENCE_TABLES:
                conn.execute(text(f"DELETE FROM {table.name}"))


@pytest.fixture
def client(engine):
    from app.main import app

    with TestClient(app) as c:
        yield c


def register(client, email="cand@example.com", password="Passw0rd!", role="candidate", **extra):
    payload = {"email": email, "password": password, "role": role, "consent_processing": True, **extra}
    return client.post("/api/auth/register", json=payload)


def register_and_verify(client, email="cand@example.com", password="Passw0rd!", role="candidate", **extra):
    r = register(client, email, password, role, **extra)
    assert r.status_code == 201, r.text
    code = r.json()["dev_verification_code"]
    r = client.post("/api/auth/verify-email", json={"email": email, "code": code})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]
