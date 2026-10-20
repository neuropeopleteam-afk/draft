"""data_ml.train_time.middle_solve_g_k2 — mcq_concept (Middle). Время распределённого обучения модели — обратная задача: наименьший допустимый вход «число GPU» с учётом: число GPU, эффективность масштабирования.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«train_time» в families/_w2010_scale_cat_data_ml.py, ступень 2 из 5, обратная задача по «g»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_ml.train_time.middle_solve_g_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
