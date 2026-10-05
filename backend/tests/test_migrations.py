from sqlalchemy import inspect

from app.models import metadata


def test_migrations_match_models(engine):
    """Все таблицы моделей созданы миграциями (схема не расходится с кодом)."""
    existing = set(inspect(engine).get_table_names())
    assert set(metadata.tables) <= existing
