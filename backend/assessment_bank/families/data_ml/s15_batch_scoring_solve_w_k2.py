"""data_ml.batch_scoring.middle_solve_w_k2 — mcq_concept (Middle). Окно ночного пакетного скоринга — обратная задача: наименьший допустимый вход «число воркеров» с учётом: воркеры, запас загрузки.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«batch_scoring» в families/_w2010_scale_cat_data_ml.py, ступень 2 из 5, обратная задача по «w»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_ml.batch_scoring.middle_solve_w_k2"
N_ABOVE = (0, 1)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
