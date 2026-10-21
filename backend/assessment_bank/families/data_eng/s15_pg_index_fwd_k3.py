"""data_eng.pg_index.junior_fwd_k3 — mcq_concept (Junior). Размер B-tree-индекса PostgreSQL — прямой расчёт с учётом: fillfactor, внутренние страницы, bloat.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«pg_index» в families/_w2010_scale_cat_data_eng.py, ступень 3 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'data_eng.pg_index.junior_fwd_k3'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
