"""analyst.er_table_growth.principal_solve_ev_k5 — mcq_concept (Principal). Прогноз годового роста связующей таблицы в ER-модели БД — обратная задача: наибольший допустимый вход «записей на клиента в месяц» с учётом: историчность SCD2, составные индексы, запас fillfactor, архивация старых строк, справочники.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«er_table_growth» в families/_w2010_scale_cat_analyst.py, ступень 5 из 5, обратная задача по «ev»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "analyst.er_table_growth.principal_solve_ev_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
