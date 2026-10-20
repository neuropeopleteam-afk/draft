"""backend.kafka_consumers.lead_solve_mu_k4 — mcq_concept (Lead). Число консьюмеров и партиций Kafka-топика — обратная задача: наименьший допустимый вход «производительность консьюмера, сообщений в минуту» с учётом: запас по загрузке, рост потока, повторная обработка, запас на выкатку.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«kafka_consumers» в families/_w2010_scale_cat_backend.py, ступень 4 из 5, обратная задача по «mu»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "backend.kafka_consumers.lead_solve_mu_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
