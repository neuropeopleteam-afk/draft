"""analyst.principal.peak_rps_mcq — mcq_concept (Principal). Пиковый RPS для НФТ из бизнес-метрик — DAU, действия, запросы на действие, пиковый час и минутные пики.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["analyst.principal.peak_rps_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "analyst.principal.peak_rps_mcq"
generate = make(FAMILY_ID)
