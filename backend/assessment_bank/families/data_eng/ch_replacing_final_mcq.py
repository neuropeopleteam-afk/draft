"""data_eng.clickhouse.ch_replacing_final_mcq — mcq_concept (Senior/Lead). ClickHouse: count() FINAL у ReplacingMergeTree — схлопывание по ключу сортировки, версия в ключ не входит.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["data_eng.clickhouse.ch_replacing_final_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "data_eng.clickhouse.ch_replacing_final_mcq"
generate = make(FAMILY_ID)
