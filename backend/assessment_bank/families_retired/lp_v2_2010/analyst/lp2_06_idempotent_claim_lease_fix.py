"""analyst.lead_v2.idempotent_claim_lease_fix — choose_fix (senior, lead). Системный и бизнес-анализ: Атомарный захват ключа идемпотентности с перехватом просроченного лиза.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'analyst.lead_v2.idempotent_claim_lease_fix'
generate = make_lp_v2('analyst', 6)
