"""data_eng.storage.principal_tiering_cost_mcq — mcq_concept (Principal). Стоимость горячего и холодного хранения — репликация горячего слоя, сжатие холодного, установившийся режим.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["data_eng.storage.principal_tiering_cost_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "data_eng.storage.principal_tiering_cost_mcq"
generate = make(FAMILY_ID)
