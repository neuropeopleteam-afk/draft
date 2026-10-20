"""data_eng.cdc_catchup.intern_fwd_k2 — mcq_concept (Стажёр). Время догона отставания CDC-репликации — прямой расчёт с учётом: запас на пик, дубликаты.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«cdc_catchup» в families/_w2010_scale_cat_data_eng.py, ступень 2 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_eng.cdc_catchup.intern_fwd_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
