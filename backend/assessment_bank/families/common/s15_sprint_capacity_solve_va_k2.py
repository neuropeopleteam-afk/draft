"""common.sprint_capacity.middle_solve_va_k2 — mcq_concept (Middle). Ёмкость спринта команды в стори-пойнтах — обратная задача: наибольший допустимый вход «доля отпусков и дежурств, %» с учётом: отпуска и дежурства, встречи и ревью.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«sprint_capacity» в families/_w2010_scale_cat_common.py, ступень 2 из 5, обратная задача по «va»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "common.sprint_capacity.middle_solve_va_k2"
N_ABOVE = (3,)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
