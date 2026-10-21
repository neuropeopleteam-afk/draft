"""devops.principal_v2.outbox_atomic_reclaim_fix — choose_fix (principal). DevOps и SRE: Повторный захват зависших сообщений transactional outbox без дублей.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'devops.principal_v2.outbox_atomic_reclaim_fix'
generate = make_lp_v2('devops', 11)
