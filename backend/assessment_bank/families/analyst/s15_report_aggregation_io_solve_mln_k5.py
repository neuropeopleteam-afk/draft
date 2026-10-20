"""analyst.report_aggregation_io.lead_solve_mln_k5 — mcq_concept (Principal). Объём сканируемых данных при построении аналитической сводки — обратная задача: наибольший допустимый вход «число строк в таблице фактов, млн» с учётом: отсечение партиций, колоночная проекция, чтение таблиц JOIN, временная материализация, справочники и метаданные.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«report_aggregation_io» в families/_w2010_scale_cat_analyst.py, ступень 5 из 5, обратная задача по «mln»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "analyst.report_aggregation_io.lead_solve_mln_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
