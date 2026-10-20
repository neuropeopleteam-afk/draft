"""backend.idem_redis.intern_fwd_k2 — mcq_concept (Стажёр). Память Redis под ключи идемпотентности — прямой расчёт с учётом: накладные расходы Redis, фрагментация.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«idem_redis» в families/_w2010_scale_cat_backend.py, ступень 2 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "backend.idem_redis.intern_fwd_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
