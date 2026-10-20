"""security.principal.password_hash_budget_mcq — mcq_concept (Principal). Время хэша Argon2id в пик входов — ограничение по CPU с долей под хэши и по памяти на хэш (закон Литтла).

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["security.principal.password_hash_budget_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "security.principal.password_hash_budget_mcq"
generate = make(FAMILY_ID)
