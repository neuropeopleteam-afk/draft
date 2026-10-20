"""backend.pgpool.junior_fwd_k3 — mcq_concept (Junior). Размер пула соединений PostgreSQL по закону Литтла — прямой расчёт с учётом: пиковый коэффициент, запас утилизации, ретраи.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«pgpool» в families/_w2010_scale_cat_backend.py, ступень 3 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "backend.pgpool.junior_fwd_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
