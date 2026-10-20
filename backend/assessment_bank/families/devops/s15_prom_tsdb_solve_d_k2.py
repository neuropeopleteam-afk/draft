"""devops.prom_tsdb.middle_solve_d_k2 — mcq_concept (Middle). Диск Prometheus под временные ряды — обратная задача: наибольший допустимый вход «retention, дней» с учётом: индексы, WAL.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«prom_tsdb» в families/_w2010_scale_cat_devops.py, ступень 2 из 5, обратная задача по «d»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "devops.prom_tsdb.middle_solve_d_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
