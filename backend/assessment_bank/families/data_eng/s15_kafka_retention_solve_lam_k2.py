"""data_eng.kafka_retention.junior_solve_lam_k2 — mcq_concept (Junior). Диск под топик Kafka с учётом retention и репликации — обратная задача: наибольший допустимый вход «поток сообщений в секунду» с учётом: репликация, сжатие.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«kafka_retention» в families/_w2010_scale_cat_data_eng.py, ступень 2 из 5, обратная задача по «lam»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_eng.kafka_retention.junior_solve_lam_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
