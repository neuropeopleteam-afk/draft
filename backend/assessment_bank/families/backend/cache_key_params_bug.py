"""backend.cache.key_params_bug — ключ кэша без параметра запроса.

Выделено из backend.cache_invalidation_bug (cache_invalidation_bug) по итогам калибровки панелью LLM 05.10:
варианты исходного семейства были неизоморфны (σ > 0,5 и χ² p < 0,01), разброс объяснялся
подтипом дефекта. Генератор общий, подтип фиксирован.
"""
from __future__ import annotations

from assessment_bank.families.backend.cache_invalidation_bug import _generate

FAMILY_ID = "backend.cache.key_params_bug"
SUBTYPES = ('key_missing_param',)


def generate(seed: int):
    return _generate(seed, FAMILY_ID, SUBTYPES)
