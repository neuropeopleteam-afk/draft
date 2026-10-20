"""analyst.gateway_retry_sla.middle_solve_rt_k3 — mcq_concept (Middle). Бюджет времени синхронного вызова внешнего шлюза с таймаутами — обратная задача: наибольший допустимый вход «время ответа внешнего партнёра, мс» с учётом: число попыток, пауза backoff, проверка идемпотентности.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«gateway_retry_sla» в families/_w2010_scale_cat_analyst.py, ступень 3 из 5, обратная задача по «rt»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "analyst.gateway_retry_sla.middle_solve_rt_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
