"""backend.idem_redis.junior_fwd_k3 — mcq_concept (Junior). Память Redis под ключи идемпотентности — прямой расчёт с учётом: накладные расходы Redis, фрагментация, запас maxmemory.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«idem_redis» в families/_w2010_scale_cat_backend.py, ступень 3 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'backend.idem_redis.junior_fwd_k3'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
