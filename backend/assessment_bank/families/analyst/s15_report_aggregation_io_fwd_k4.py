"""analyst.report_aggregation_io.middle_fwd_k4 — mcq_concept (Middle). Объём сканируемых данных при построении аналитической сводки — прямой расчёт с учётом: отсечение партиций, колоночная проекция, чтение таблиц JOIN, временная материализация.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«report_aggregation_io» в families/_w2010_scale_cat_analyst.py, ступень 4 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'analyst.report_aggregation_io.middle_fwd_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
