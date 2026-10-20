"""analyst.report_aggregation_io.intern_fwd_k2 — mcq_concept (Стажёр). Объём сканируемых данных при построении аналитической сводки — прямой расчёт с учётом: отсечение партиций, колоночная проекция.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«report_aggregation_io» в families/_w2010_scale_cat_analyst.py, ступень 2 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "analyst.report_aggregation_io.intern_fwd_k2"
N_ABOVE = (1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
