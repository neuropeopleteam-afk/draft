"""backend.pgpool.lead_solve_lam_k5 — mcq_concept (Principal). Размер пула соединений PostgreSQL по закону Литтла — обратная задача: наибольший допустимый вход «поток запросов в секунду» с учётом: пиковый коэффициент, запас утилизации, ретраи, число экземпляров, резерв соединений.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«pgpool» в families/_w2010_scale_cat_backend.py, ступень 5 из 5, обратная задача по «lam»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "backend.pgpool.lead_solve_lam_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
