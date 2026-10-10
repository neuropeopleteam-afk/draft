"""Я7 (10.10): пул соединений с БД из настроек и 503 db_busy вместо 500, когда соединение не дождались.

Нагрузка 100 пользователей на стенде (docs/LOAD.md, раздел 6): пул 5 + 10 на воркер при 40 потоках FastAPI исчерпывался,
запросы ждали соединение 30 с и падали 500 — у части экспертов белый экран. Теперь размер пула и ожидание — из
настроек (DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_TIMEOUT_S), а исчерпание — 503 с Retry-After и кодом db_busy.
"""
from __future__ import annotations

import time

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core import db as dbmod
from app.core.config import get_settings


def test_pool_settings_reach_engine(engine):
    s = get_settings()
    assert (s.db_pool_size, s.db_max_overflow, s.db_pool_timeout_s) == (8, 10, 10.0)
    pool = dbmod.get_engine().pool
    assert pool.size() == s.db_pool_size and pool._max_overflow == s.db_max_overflow and pool._timeout == 10.0
    # бюджет docker-compose.yml: 2 воркера × (8 + 10) + Keycloak 6 + резерв 3 + обслуживание 5 ≤ max_connections 50
    assert 2 * (s.db_pool_size + s.db_max_overflow) + 6 + 3 + 5 <= 50


def test_pool_exhausted_gives_503_db_busy_with_retry_after(client, engine):
    """Единственное соединение крошечного пула занято — запрос к API ждёт pool_timeout и получает 503 db_busy."""
    from app.main import app

    tiny = create_engine(engine.url, pool_size=1, max_overflow=0, pool_timeout=0.3,
                         connect_args={"check_same_thread": False})
    Tiny = sessionmaker(bind=tiny, autoflush=False, expire_on_commit=False)

    def tiny_db():
        s = Tiny()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[dbmod.get_db] = tiny_db
    held = tiny.connect()
    held.execute(text("select 1"))
    try:
        t0 = time.time()
        r = client.get("/api/catalog")
        assert r.status_code == 503, r.text
        assert r.headers["retry-after"] == str(get_settings().db_busy_retry_after_s)
        assert r.json()["detail"]["code"] == "db_busy" and "повторите" in r.json()["detail"]["message"]
        assert time.time() - t0 < 5
    finally:
        held.close()
        app.dependency_overrides.pop(dbmod.get_db, None)
        tiny.dispose()
    assert client.get("/api/catalog").status_code == 200  # соединение освободилось — обычный ответ


def test_release_returns_connection_and_keeps_objects(engine):
    """db.release(): соединение возвращается в пул до долгой работы без БД, загруженные объекты доступны."""
    from app.modules.catalog.models import Direction

    with dbmod.SessionLocal() as s:
        d = s.query(Direction).first()
        assert s.connection() is not None and s.in_transaction()
        dbmod.release(s)
        assert not s.in_transaction()
        assert d is None or d.title  # объект не «протух» после фиксации (expire_on_commit=False)


def test_validation_report_cached_single_flight(client, monkeypatch):
    """/api/validation/report: при TTL > 0 считает один поток, остальные получают готовые байты; содержимое — то же,
    что без кэша; соединение с БД возвращается в пул до сериализации."""
    import json
    import threading

    from app.modules.validation import router as vr

    fresh = client.get("/api/validation/report").json()  # TTL 0 (conftest) — как раньше, на каждый запрос
    calls = []
    orig = vr._report_body

    def slow(db):
        calls.append(1)
        time.sleep(0.3)
        return orig(db)

    monkeypatch.setattr(get_settings(), "validation_report_ttl_s", 30.0)
    monkeypatch.setattr(vr, "_report_body", slow)
    monkeypatch.setattr(vr, "_rep_cache", {})
    released = []
    monkeypatch.setattr(vr, "release", lambda db: released.append(db.in_transaction()) or db.commit())
    out: list = []

    def one():
        with dbmod.SessionLocal() as s:
            out.append(vr.report(s).body)

    ts = [threading.Thread(target=one) for _ in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=30)
    assert len(out) == 6 and len(set(out)) == 1 and len(calls) == 1 and released == [True]
    assert json.loads(out[0]).keys() == fresh.keys()
    r = client.get("/api/validation/report")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json") and len(calls) == 1
    assert r.json()["live"] == json.loads(out[0])["live"]
