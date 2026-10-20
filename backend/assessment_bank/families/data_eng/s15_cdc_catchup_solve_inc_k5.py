"""data_eng.cdc_catchup.principal_solve_inc_k5 — mcq_concept (Principal). Время догона отставания CDC-репликации — обратная задача: наибольший допустимый вход «входящий поток, тыс. событий в секунду» с учётом: запас на пик, дубликаты, пересоздание индексов, батчевое применение, прогрев.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«cdc_catchup» в families/_w2010_scale_cat_data_eng.py, ступень 5 из 5, обратная задача по «inc»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_eng.cdc_catchup.principal_solve_inc_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
