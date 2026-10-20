"""backend.api_bandwidth.middle_solve_s_k2 — mcq_concept (Middle). Пропускная способность канала для ответов API — обратная задача: наибольший допустимый вход «размер ответа, КБ» с учётом: сжатие gzip, заголовки и TLS.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«api_bandwidth» в families/_w2010_scale_cat_backend.py, ступень 2 из 5, обратная задача по «s»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "backend.api_bandwidth.middle_solve_s_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
