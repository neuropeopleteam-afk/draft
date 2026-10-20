"""backend.api_bandwidth.senior_solve_lam_k4 — mcq_concept (Lead). Пропускная способность канала для ответов API — обратная задача: наибольший допустимый вход «ответов в секунду» с учётом: сжатие gzip, заголовки и TLS, пиковый коэффициент, запас канала.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«api_bandwidth» в families/_w2010_scale_cat_backend.py, ступень 4 из 5, обратная задача по «lam»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "backend.api_bandwidth.senior_solve_lam_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
