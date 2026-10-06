"""data_ml.metrics.auc_pairwise_ties_bug — попарный ROC-AUC: ничьи поглощены сравнением >=.

Выделено из data_ml.metrics_roc_auc_ties_bug (metrics_roc_auc_ties_bug) по итогам калибровки панелью LLM 05.10:
варианты исходного семейства были неизоморфны (σ > 0,5 и χ² p < 0,01), разброс объяснялся
подтипом дефекта. Генератор общий, подтип фиксирован.
"""
from __future__ import annotations

from assessment_bank.families.data_ml.metrics_roc_auc_ties_bug import _generate

FAMILY_ID = "data_ml.metrics.auc_pairwise_ties_bug"
SUBTYPES = ('pair_ge',)


def generate(seed: int):
    return _generate(seed, FAMILY_ID, SUBTYPES)
