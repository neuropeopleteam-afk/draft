"""common.git.move_commits_mcq — перенос ошибочных коммитов из main в новую ветку.

Выделено из common.git_undo_mcq (git_undo_mcq) по итогам калибровки панелью LLM 05.10:
варианты исходного семейства были неизоморфны (σ > 0,5 и χ² p < 0,01), разброс объяснялся
подтипом дефекта. Генератор общий, подтип фиксирован.
"""
from __future__ import annotations

from assessment_bank.families_retired.form_leak_2110.common.git_undo_mcq import _generate

FAMILY_ID = "common.git.move_commits_mcq"
SUBTYPES = ('move',)


def generate(seed: int):
    return _generate(seed, FAMILY_ID, SUBTYPES)
