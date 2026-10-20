"""data_eng.cdc_catchup.senior_solve_bl_k4 — mcq_concept (Lead). Время догона отставания CDC-репликации — обратная задача: наибольший допустимый вход «накопленное отставание, млн событий» с учётом: запас на пик, дубликаты, пересоздание индексов, батчевое применение.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«cdc_catchup» в families/_w2010_scale_cat_data_eng.py, ступень 4 из 5, обратная задача по «bl»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_eng.cdc_catchup.senior_solve_bl_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
