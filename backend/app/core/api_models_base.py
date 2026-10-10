"""Основа моделей ответов для документации OpenAPI (Я3): общий базовый класс и псевдоним «объект с произвольными полями».

Отдельный файл, чтобы модули api_models*.py могли импортировать основу без круговых зависимостей.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

Obj = dict[str, Any]


class Doc(BaseModel):
    # Модель только для документации: лишние поля допустимы (перечень не исчерпывающий), имена — и по алиасам, и по полям.
    # Строки документации здесь нет намеренно: иначе она попала бы в описание каждой схемы-наследника.
    model_config = ConfigDict(extra="allow", populate_by_name=True)
