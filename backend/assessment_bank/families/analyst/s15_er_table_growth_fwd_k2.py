"""analyst.er_table_growth.intern_fwd_k2 — mcq_concept (Стажёр). Прогноз годового роста связующей таблицы в ER-модели БД — прямой расчёт с учётом: историчность SCD2, составные индексы.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«er_table_growth» в families/_w2010_scale_cat_analyst.py, ступень 2 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "analyst.er_table_growth.intern_fwd_k2"
N_ABOVE = (0, 1, 2)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
