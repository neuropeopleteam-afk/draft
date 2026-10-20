"""analyst.integration.kafka_lag_catchup_mcq — mcq_concept (Senior/Lead). Интеграция через Kafka: время догона лага после пика для требований к задержке.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["analyst.integration.kafka_lag_catchup_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "analyst.integration.kafka_lag_catchup_mcq"
generate = make(FAMILY_ID)
