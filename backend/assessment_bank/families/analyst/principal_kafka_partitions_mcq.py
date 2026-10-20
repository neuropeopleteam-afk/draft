"""analyst.principal.kafka_partitions_mcq — mcq_concept (Principal). Число партиций топика в требованиях — рост, запас и узкое место консьюмера, партиции потом не меняют.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["analyst.principal.kafka_partitions_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "analyst.principal.kafka_partitions_mcq"
generate = make(FAMILY_ID)
