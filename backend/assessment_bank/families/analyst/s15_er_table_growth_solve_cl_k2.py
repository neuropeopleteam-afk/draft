"""analyst.er_table_growth.junior_solve_cl_k2 — mcq_concept (Junior). Прогноз годового роста связующей таблицы в ER-модели БД — обратная задача: наибольший допустимый вход «число активных клиентов, тыс.» с учётом: историчность SCD2, составные индексы.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«er_table_growth» в families/_w2010_scale_cat_analyst.py, ступень 2 из 5, обратная задача по «cl»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "analyst.er_table_growth.junior_solve_cl_k2"
N_ABOVE = (1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
