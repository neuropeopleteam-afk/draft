"""qa.manual.manual_pairwise_bound_mcq — mcq_concept (Senior/Lead). Ручное тестирование: нижняя граница pairwise — произведение двух самых «широких» параметров.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["qa.manual.manual_pairwise_bound_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "qa.manual.manual_pairwise_bound_mcq"
generate = make(FAMILY_ID)
