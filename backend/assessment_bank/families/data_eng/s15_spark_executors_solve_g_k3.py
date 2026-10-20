"""data_eng.spark_executors.middle_solve_g_k3 — mcq_concept (Middle). Число executor-ов Spark для джоба в срок — обратная задача: наибольший допустимый вход «объём входных данных, ГБ» с учётом: ядра executor-а, shuffle, перекос партиций.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«spark_executors» в families/_w2010_scale_cat_data_eng.py, ступень 3 из 5, обратная задача по «g»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_eng.spark_executors.middle_solve_g_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
