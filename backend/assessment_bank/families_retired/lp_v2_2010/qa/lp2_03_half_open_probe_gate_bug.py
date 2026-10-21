"""qa.lead_v2.half_open_probe_gate_bug — find_bug (lead). Обеспечение качества (QA): Лавина пробных запросов в полуоткрытом состоянии предохранителя.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'qa.lead_v2.half_open_probe_gate_bug'
generate = make_lp_v2('qa', 3)
