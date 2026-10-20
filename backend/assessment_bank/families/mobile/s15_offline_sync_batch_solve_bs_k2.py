"""mobile.offline_sync_batch.middle_solve_bs_k2 — mcq_concept (Middle). Длительность фоновой синхронизации локальной БД устройства — обратная задача: наименьший допустимый вход «размер пачки, записей» с учётом: схлопывание правок, повторы сети.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«offline_sync_batch» в families/_w2010_scale_cat_mobile.py, ступень 2 из 5, обратная задача по «bs»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "mobile.offline_sync_batch.middle_solve_bs_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
