"""data_eng.ch_storage.lead_solve_c_k4 — mcq_concept (Middle). Объём таблицы ClickHouse за период хранения — обратная задача: наименьший допустимый вход «степень сжатия, раз» с учётом: сжатие, реплики, слияния кусков, запас диска.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«ch_storage» в families/_w2010_scale_cat_data_eng.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'data_eng.ch_storage.lead_solve_c_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
