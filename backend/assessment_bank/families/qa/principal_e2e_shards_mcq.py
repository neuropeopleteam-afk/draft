"""qa.principal.e2e_shards_mcq — mcq_concept (Principal). Шардирование e2e — жадная раздача неделимых тестов, длинный тест и подготовка шарда против суммы, делённой на шарды.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["qa.principal.e2e_shards_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "qa.principal.e2e_shards_mcq"
generate = make(FAMILY_ID)
