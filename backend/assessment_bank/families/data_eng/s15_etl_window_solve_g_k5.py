"""data_eng.etl_window.lead_solve_g_k5 — mcq_concept (Senior). Длительность ночного ETL-окна — обратная задача: наибольший допустимый вход «объём за ночь, ГБ» с учётом: потоки, трансформации, перезапуски, рост данных, проверки качества.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«etl_window» в families/_w2010_scale_cat_data_eng.py, ступень 5 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'data_eng.etl_window.lead_solve_g_k5'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
