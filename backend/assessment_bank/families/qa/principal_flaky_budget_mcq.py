"""qa.principal.flaky_budget_mcq — mcq_concept (Principal). Допустимая нестабильность попытки теста — перезапуски возводят в степень, N тестов, цель по ложно-красным прогонам.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["qa.principal.flaky_budget_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "qa.principal.flaky_budget_mcq"
generate = make(FAMILY_ID)
