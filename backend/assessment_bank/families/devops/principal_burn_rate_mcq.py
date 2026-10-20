"""devops.sre.principal_burn_rate_mcq — mcq_concept (Principal). Алерт по burn rate — доля ошибок, при которой за окно сгорает X % месячного бюджета SLO.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["devops.sre.principal_burn_rate_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "devops.sre.principal_burn_rate_mcq"
generate = make(FAMILY_ID)
