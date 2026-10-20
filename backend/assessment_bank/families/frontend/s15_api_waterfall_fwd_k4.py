"""frontend.api_waterfall.middle_fwd_k4 — mcq_concept (Middle). Водопад запросов экрана и время до данных — прямой расчёт с учётом: независимые запросы, очередь HTTP/1.1, SWR-кэш, запас на p95.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«api_waterfall» в families/_w2010_scale_cat_frontend.py, ступень 4 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "frontend.api_waterfall.middle_fwd_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
