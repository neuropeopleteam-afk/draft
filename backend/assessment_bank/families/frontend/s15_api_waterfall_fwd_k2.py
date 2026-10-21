"""frontend.api_waterfall.intern_fwd_k2 — mcq_concept (Стажёр). Водопад запросов экрана и время до данных — прямой расчёт с учётом: независимые запросы, очередь HTTP/1.1.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«api_waterfall» в families/_w2010_scale_cat_frontend.py, ступень 2 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'frontend.api_waterfall.intern_fwd_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
