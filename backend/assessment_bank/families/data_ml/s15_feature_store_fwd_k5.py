"""data_ml.feature_store.senior_fwd_k5 — mcq_concept (Senior). Память онлайн-хранилища признаков — прямой расчёт с учётом: ключи, репликация, рост, запас памяти, служебные структуры.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«feature_store» в families/_w2010_scale_cat_data_ml.py, ступень 5 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'data_ml.feature_store.senior_fwd_k5'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
