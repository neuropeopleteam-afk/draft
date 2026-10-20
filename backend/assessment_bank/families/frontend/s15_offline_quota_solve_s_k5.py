"""frontend.offline_quota.principal_solve_s_k5 — mcq_concept (Principal). Объём офлайн-кэша PWA в IndexedDB — обратная задача: наибольший допустимый вход «размер записи, КБ» с учётом: индексы, версии записей, сжатие, запас квоты, статика.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«offline_quota» в families/_w2010_scale_cat_frontend.py, ступень 5 из 5, обратная задача по «s»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "frontend.offline_quota.principal_solve_s_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
