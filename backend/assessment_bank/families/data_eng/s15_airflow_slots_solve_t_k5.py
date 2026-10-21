"""data_eng.airflow_slots.principal_solve_t_k5 — mcq_concept (Senior). Число слотов воркеров Airflow для ночного расписания — обратная задача: наибольший допустимый вход «длительность задачи, мин» с учётом: пиковый коэффициент, ретраи, запас слотов, слоты на воркер, сенсоры.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«airflow_slots» в families/_w2010_scale_cat_data_eng.py, ступень 5 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'data_eng.airflow_slots.principal_solve_t_k5'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
