"""data_ml.sql.rolling_partition_bug — скользящее окно без PARTITION BY.

Выделено из data_ml.sql_rolling_window_bug (sql_rolling_window_bug) по итогам калибровки панелью LLM 05.10:
варианты исходного семейства были неизоморфны (σ > 0,5 и χ² p < 0,01), разброс объяснялся
подтипом дефекта. Генератор общий, подтип фиксирован.
"""
from __future__ import annotations

from assessment_bank.families.data_ml.sql_rolling_window_bug import _generate

FAMILY_ID = "data_ml.sql.rolling_partition_bug"
SUBTYPES = ('no_partition',)


def generate(seed: int):
    return _generate(seed, FAMILY_ID, SUBTYPES)
