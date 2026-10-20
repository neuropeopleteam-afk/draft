"""data_eng.pg.pg_partition_pruning_mcq — mcq_concept (Senior/Lead). PostgreSQL: отсечение секций для диапазона дат — строгая правая граница, неполный первый месяц, DEFAULT.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["data_eng.pg.pg_partition_pruning_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "data_eng.pg.pg_partition_pruning_mcq"
generate = make(FAMILY_ID)
