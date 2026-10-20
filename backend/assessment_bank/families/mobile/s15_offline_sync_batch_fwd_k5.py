"""mobile.offline_sync_batch.senior_fwd_k5 — mcq_concept (Senior). Длительность фоновой синхронизации локальной БД устройства — прямой расчёт с учётом: схлопывание правок, повторы сети, запись в SQLite, параллельные потоки, установка соединения.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«offline_sync_batch» в families/_w2010_scale_cat_mobile.py, ступень 5 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "mobile.offline_sync_batch.senior_fwd_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
