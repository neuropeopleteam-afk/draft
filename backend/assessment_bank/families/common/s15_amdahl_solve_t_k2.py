"""common.amdahl.middle_solve_t_k2 — mcq_concept (Middle). Время задачи на нескольких ядрах по закону Амдала — обратная задача: наибольший допустимый вход «время на одном ядре, с» с учётом: накладные расходы синхронизации, запуск.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«amdahl» в families/_w2010_scale_cat_common.py, ступень 2 из 5, обратная задача по «T»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "common.amdahl.middle_solve_t_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
