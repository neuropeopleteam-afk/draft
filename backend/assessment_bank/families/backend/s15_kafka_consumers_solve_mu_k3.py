"""backend.kafka_consumers.senior_solve_mu_k3 — mcq_concept (Senior). Число консьюмеров и партиций Kafka-топика — обратная задача: наименьший допустимый вход «производительность консьюмера, сообщений в минуту» с учётом: запас по загрузке, рост потока, повторная обработка.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«kafka_consumers» в families/_w2010_scale_cat_backend.py, ступень 3 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'backend.kafka_consumers.senior_solve_mu_k3'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
