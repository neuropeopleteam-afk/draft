"""analyst.gateway_retry_sla.middle_solve_mp_k2 — mcq_concept (Middle). Бюджет времени синхронного вызова внешнего шлюза с таймаутами — обратная задача: наибольший допустимый вход «время маппинга полей, мс» с учётом: число попыток, пауза backoff.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«gateway_retry_sla» в families/_w2010_scale_cat_analyst.py, ступень 2 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'analyst.gateway_retry_sla.middle_solve_mp_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
