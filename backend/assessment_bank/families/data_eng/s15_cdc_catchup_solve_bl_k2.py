"""data_eng.cdc_catchup.junior_solve_bl_k2 — mcq_concept (Junior). Время догона отставания CDC-репликации — обратная задача: наибольший допустимый вход «накопленное отставание, млн событий» с учётом: запас на пик, дубликаты.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«cdc_catchup» в families/_w2010_scale_cat_data_eng.py, ступень 2 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'data_eng.cdc_catchup.junior_solve_bl_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
