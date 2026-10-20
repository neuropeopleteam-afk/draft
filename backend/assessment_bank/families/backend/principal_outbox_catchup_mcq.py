"""backend.outbox.principal_outbox_catchup_mcq — mcq_concept (Principal). Transactional outbox после простоя брокера — сколько relay-воркеров разберут накопленное за срок при продолжающемся потоке.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["backend.outbox.principal_outbox_catchup_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "backend.outbox.principal_outbox_catchup_mcq"
generate = make(FAMILY_ID)
