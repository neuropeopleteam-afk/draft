"""frontend.api_waterfall.senior_solve_n_k3 — mcq_concept (Senior). Водопад запросов экрана и время до данных — обратная задача: наибольший допустимый вход «число запросов экрана» с учётом: независимые запросы, очередь HTTP/1.1, SWR-кэш.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«api_waterfall» в families/_w2010_scale_cat_frontend.py, ступень 3 из 5, обратная задача по «n»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "frontend.api_waterfall.senior_solve_n_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
