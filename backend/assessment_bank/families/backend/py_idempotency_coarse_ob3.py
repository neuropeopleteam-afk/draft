"""backend.py.idempotency_coarse_ob3 — слишком грубый ключ дедупликации вебхуков.

Выделено из backend.py_idempotency_ob3 (py_idempotency_ob3) по итогам калибровки панелью LLM 05.10:
варианты исходного семейства были неизоморфны (σ > 0,5 и χ² p < 0,01), разброс объяснялся
подтипом дефекта. Генератор общий, подтип фиксирован.
"""
from __future__ import annotations

from assessment_bank.families.backend.py_idempotency_ob3 import _generate

FAMILY_ID = "backend.py.idempotency_coarse_ob3"
SUBTYPES = ('coarse',)


def generate(seed: int):
    return _generate(seed, FAMILY_ID, SUBTYPES)
