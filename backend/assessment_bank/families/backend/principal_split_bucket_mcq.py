"""backend.ratelimit.principal_split_bucket_mcq — mcq_concept (Principal). Локальные token bucket на шлюзах — ёмкость и скорость, делённые на число шлюзов, неравномерная привязка клиента.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["backend.ratelimit.principal_split_bucket_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "backend.ratelimit.principal_split_bucket_mcq"
generate = make(FAMILY_ID)
