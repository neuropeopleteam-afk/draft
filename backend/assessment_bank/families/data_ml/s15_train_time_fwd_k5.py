"""data_ml.train_time.senior_fwd_k5 — mcq_concept (Senior). Время распределённого обучения модели — прямой расчёт с учётом: число GPU, эффективность масштабирования, чекпойнты, падения spot, подготовка.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«train_time» в families/_w2010_scale_cat_data_ml.py, ступень 5 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'data_ml.train_time.senior_fwd_k5'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
