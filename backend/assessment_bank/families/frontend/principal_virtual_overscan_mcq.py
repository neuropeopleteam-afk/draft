"""frontend.perf.principal_virtual_overscan_mcq — mcq_concept (Principal). Виртуальный список на 90/120 Гц — наибольший overscan с двух сторон при стоимости рендера и layout строки.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["frontend.perf.principal_virtual_overscan_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "frontend.perf.principal_virtual_overscan_mcq"
generate = make(FAMILY_ID)
