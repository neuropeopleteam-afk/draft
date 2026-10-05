"""Банк заданий: чистый Python без БД, импортируется бэкендом.

Семейство = YAML-описание + генератор ``generate(seed: int) -> Variant``.
Формат зафиксирован в брифе и docs/ARCHITECTURE.md; наполнение банка — отдельная задача.
"""
from assessment_bank.types import Family, Variant

__all__ = ["Family", "Variant"]
