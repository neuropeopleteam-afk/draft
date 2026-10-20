"""mobile.offline_sync_batch.senior_solve_rec_k4 — mcq_concept (Senior). Длительность фоновой синхронизации локальной БД устройства — обратная задача: наибольший допустимый вход «накопившихся изменений» с учётом: схлопывание правок, потери попыток сети, запись в SQLite, параллельные потоки.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«offline_sync_batch» в families/_w2010_scale_cat_mobile.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'mobile.offline_sync_batch.senior_solve_rec_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
