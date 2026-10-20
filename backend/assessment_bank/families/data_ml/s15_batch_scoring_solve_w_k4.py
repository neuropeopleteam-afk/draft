"""data_ml.batch_scoring.lead_solve_w_k4 — mcq_concept (Middle). Окно ночного пакетного скоринга — обратная задача: наименьший допустимый вход «число воркеров» с учётом: воркеры, запас загрузки, чтение признаков, перезапуск партиций.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«batch_scoring» в families/_w2010_scale_cat_data_ml.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'data_ml.batch_scoring.lead_solve_w_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
