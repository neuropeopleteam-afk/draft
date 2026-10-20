"""backend.api_bandwidth.senior_fwd_k5 — mcq_concept (Senior). Пропускная способность канала для ответов API — прямой расчёт с учётом: сжатие gzip, заголовки и TLS, пиковый коэффициент, запас канала, каналы в дата-центрах.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«api_bandwidth» в families/_w2010_scale_cat_backend.py, ступень 5 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "backend.api_bandwidth.senior_fwd_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
