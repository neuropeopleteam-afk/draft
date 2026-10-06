"""frontend.sec.replace_global_bug — replace без флага g в функции экранирования.

Выделено из frontend.sec_escape_html_bug (sec_escape_html_bug) по итогам калибровки панелью LLM 05.10:
варианты исходного семейства были неизоморфны (σ > 0,5 и χ² p < 0,01), разброс объяснялся
подтипом дефекта. Генератор общий, подтип фиксирован.
"""
from __future__ import annotations

from assessment_bank.families.frontend.sec_escape_html_bug import _generate

FAMILY_ID = "frontend.sec.replace_global_bug"
SUBTYPES = ('no_global_lt', 'no_global_quot')


def generate(seed: int):
    return _generate(seed, FAMILY_ID, SUBTYPES)
