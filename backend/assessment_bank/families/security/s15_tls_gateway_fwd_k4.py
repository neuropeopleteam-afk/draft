"""security.tls_gateway.middle_fwd_k4 — mcq_concept (Middle). Число ядер шлюза терминации TLS — прямой расчёт с учётом: возобновление сессий, пиковый коэффициент, проверка mTLS, запас по загрузке.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«tls_gateway» в families/_w2010_scale_cat_security.py, ступень 4 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "security.tls_gateway.middle_fwd_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
