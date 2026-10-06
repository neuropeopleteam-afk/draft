"""frontend.ts.typeof_null_guard_bug — type guard на typeof === "object" без проверки null.

Выделено из frontend.ts_type_guard_bug (ts_type_guard_bug) по итогам калибровки панелью LLM 05.10:
варианты исходного семейства были неизоморфны (σ > 0,5 и χ² p < 0,01), разброс объяснялся
подтипом дефекта. Генератор общий, подтип фиксирован.
"""
from __future__ import annotations

from assessment_bank.families.frontend.ts_type_guard_bug import _generate

FAMILY_ID = "frontend.ts.typeof_null_guard_bug"
SUBTYPES = ('null_check',)


def generate(seed: int):
    return _generate(seed, FAMILY_ID, SUBTYPES)
