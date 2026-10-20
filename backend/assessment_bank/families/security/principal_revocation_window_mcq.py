"""security.principal.revocation_window_mcq — mcq_concept (Principal). Окно использования отозванного токена — deny-list с интервалом перечитывания, кэш проверки и срок жизни JWT с leeway.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["security.principal.revocation_window_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "security.principal.revocation_window_mcq"
generate = make(FAMILY_ID)
