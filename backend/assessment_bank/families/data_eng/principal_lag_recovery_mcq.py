"""data_eng.kafka.principal_lag_recovery_mcq — mcq_concept (Principal). Разбор лага Kafka — консьюмеров больше, чем партиций, лишние простаивают, запись продолжается.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["data_eng.kafka.principal_lag_recovery_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "data_eng.kafka.principal_lag_recovery_mcq"
generate = make(FAMILY_ID)
