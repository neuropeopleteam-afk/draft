"""qa.manual.manual_boundary_values_mcq — mcq_concept (Senior/Lead). Ручное тестирование: трёхточечный анализ граничных значений — совпадение точек в узких диапазонах.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["qa.manual.manual_boundary_values_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "qa.manual.manual_boundary_values_mcq"
generate = make(FAMILY_ID)
