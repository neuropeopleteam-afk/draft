"""analyst.async_queue_lag.senior_solve_inp_k4 — mcq_concept (Senior). Расчёт буфера асинхронной шины сообщений при пиковой подаче заявок — обратная задача: наибольший допустимый вход «входящий поток заявок/мин» с учётом: дубликаты запросов, возвраты из DLQ, резервные консьюмеры, вес сообщения.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«async_queue_lag» в families/_w2010_scale_cat_analyst.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'analyst.async_queue_lag.senior_solve_inp_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
