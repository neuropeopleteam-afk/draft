"""common.retry_backoff.principal_solve_b0_k5 — mcq_concept (Principal). Худшее время до ошибки при ретраях с экспоненциальной паузой — обратная задача: наибольший допустимый вход «первая пауза, мс» с учётом: TLS-рукопожатия, джиттер пауз, сетевые задержки, DNS-запрос, обработка ошибки.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«retry_backoff» в families/_w2010_scale_cat_common.py, ступень 5 из 5, обратная задача по «b0»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "common.retry_backoff.principal_solve_b0_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
