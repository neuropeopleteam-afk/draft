"""data_eng.airflow_slots.lead_solve_n_k5 — mcq_concept (Principal). Число слотов воркеров Airflow для ночного расписания — обратная задача: наибольший допустимый вход «число задач за ночь» с учётом: пиковый коэффициент, ретраи, запас слотов, слоты на воркер, сенсоры.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«airflow_slots» в families/_w2010_scale_cat_data_eng.py, ступень 5 из 5, обратная задача по «n»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_eng.airflow_slots.lead_solve_n_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
