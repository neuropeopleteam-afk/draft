"""qa.principal_v2.saga_lifo_compensate_bug — find_bug (principal). Обеспечение качества (QA): Нарушение обратного порядка компенсаций при откате распределённой саги.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'qa.principal_v2.saga_lifo_compensate_bug'
generate = make_lp_v2('qa', 4)
