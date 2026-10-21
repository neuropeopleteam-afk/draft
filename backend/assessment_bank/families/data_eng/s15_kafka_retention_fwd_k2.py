"""data_eng.kafka_retention.intern_fwd_k2 — mcq_concept (Стажёр). Диск под топик Kafka с учётом retention и репликации — прямой расчёт с учётом: репликация, сжатие.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«kafka_retention» в families/_w2010_scale_cat_data_eng.py, ступень 2 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'data_eng.kafka_retention.intern_fwd_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
