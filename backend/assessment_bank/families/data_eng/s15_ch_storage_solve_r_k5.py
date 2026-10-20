"""data_eng.ch_storage.lead_solve_r_k5 — mcq_concept (Principal). Объём таблицы ClickHouse за период хранения — обратная задача: наибольший допустимый вход «строк в сутки, млн» с учётом: сжатие, реплики, слияния кусков, запас диска, материализованные представления.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«ch_storage» в families/_w2010_scale_cat_data_eng.py, ступень 5 из 5, обратная задача по «r»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_eng.ch_storage.lead_solve_r_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
