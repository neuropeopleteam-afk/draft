"""analyst.async_queue_lag.senior_solve_m_k3 — mcq_concept (Senior). Расчёт буфера асинхронной шины сообщений при пиковой подаче заявок — обратная задача: наибольший допустимый вход «длительность пикового окна, мин» с учётом: дубликаты запросов, возвраты из DLQ, резервные консьюмеры.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«async_queue_lag» в families/_w2010_scale_cat_analyst.py, ступень 3 из 5, обратная задача по «m»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "analyst.async_queue_lag.senior_solve_m_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
