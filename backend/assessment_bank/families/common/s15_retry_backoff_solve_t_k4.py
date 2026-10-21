"""common.retry_backoff.senior_solve_t_k4 — mcq_concept (Senior). Худшее время до ошибки при ретраях с экспоненциальной паузой — обратная задача: наибольший допустимый вход «таймаут попытки, мс» с учётом: TLS-рукопожатия, джиттер пауз, сетевые задержки, DNS-запрос.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«retry_backoff» в families/_w2010_scale_cat_common.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'common.retry_backoff.senior_solve_t_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
