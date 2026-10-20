"""data_ml.eval.principal_precision_labeling_mcq — mcq_concept (Principal). Разметка для оценки precision на потоке — интервал для доли среди предсказанных положительных и доля таких в потоке.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["data_ml.eval.principal_precision_labeling_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "data_ml.eval.principal_precision_labeling_mcq"
generate = make(FAMILY_ID)
