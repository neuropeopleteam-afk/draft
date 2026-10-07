"""И10 (07.10): лимиты песочниц жюри под общий NAT, без ключей LLM — понятные подписи."""
from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from tests.test_infra_0610 import _login


def test_jury_sandbox_limits_defaults():
    s = Settings(_env_file=None)
    assert s.jury_sandboxes_max == 60  # было 30
    assert s.jury_new_sandboxes_per_ip_hour == 40  # было 12: жюри может сидеть за одним NAT
    assert s.jury_new_sandboxes_total_hour == 120


def test_jury_sandbox_per_ip_limit_then_shared(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "jury_new_sandboxes_per_ip_hour", 2)
    a = _login(client, "employer", "new")
    b = _login(client, "candidate", "new")
    assert a["scenario"] and b["scenario"] and a["scenario"] != b["scenario"]
    c = _login(client, "employer", "new")  # третья за час с того же адреса — общее демо, вход всё равно в один клик
    assert c["shared"] and c["scenario"] is None
    # с другого адреса (другой NAT) — своя песочница
    d = _login(client, "employer", "new", headers={"X-Forwarded-For": "8.8.4.4"})
    assert d["scenario"] and not d["shared"]


def test_jury_sandbox_total_limit_counts_db_for_all_workers(client, monkeypatch):
    from app.modules.jury import seed

    monkeypatch.setattr(get_settings(), "jury_new_sandboxes_total_hour", 2)
    first = _login(client, "employer", "new")["scenario"]
    second = _login(client, "employer", "new")["scenario"]
    with SessionLocal() as db:
        assert seed.created_last_hour(db) == 2  # счёт по БД — его видят оба воркера uvicorn
    third = _login(client, "employer", "new")
    assert first and second and third["shared"]
    # повторный вход в свою песочницу лимитом не ограничен
    again = _login(client, "employer", first)
    assert again["scenario"] == first and not again["created"]


def test_readme_demo_commands_on_fresh_sqlite(tmp_path):
    """Путь README без Docker (п. 5, «чистая» машина): миграции и демо-данные в отдельных процессах на SQLite.
    Было: `python -m app.integrations.vacancies.demo` падал на SQLite ('str' object has no attribute 'hex') —
    в отдельном процессе тип created_by (FK на users) не определялся без импорта всех моделей."""
    import os
    from pathlib import Path
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path / 'clean.db'}", "LLM_DISABLED": "true"}

    def run(*args):
        r = subprocess.run([sys.executable, *args], cwd=root, capture_output=True, text=True, timeout=300, env=env)
        assert r.returncode == 0, (args, r.stderr[-2000:])
        return r.stdout

    run("-m", "alembic", "upgrade", "head")
    assert "'candidates': 150" in run("-m", "app.modules.demo.seed")
    assert '"created": 11' in run("-m", "app.integrations.vacancies.demo")
    assert "cups" in run("-m", "app.cup.demo")
