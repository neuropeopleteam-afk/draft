"""qa.load_vusers.middle_solve_th_k2 — mcq_concept (Middle). Число виртуальных пользователей в нагрузочном тесте — обратная задача: наибольший допустимый вход «пауза пользователя, с» с учётом: пиковый коэффициент, запас на ошибки.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«load_vusers» в families/_w2010_scale_cat_qa.py, ступень 2 из 5, обратная задача по «th»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "qa.load_vusers.middle_solve_th_k2"
N_ABOVE = (1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
