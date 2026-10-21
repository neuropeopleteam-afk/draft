"""security.principal_v2.tail_latency_slo_budget_oa — open_answer (principal). Информационная безопасность: Системная архитектура удержания p99 в жёстком SLO при десятикратных пиках.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'security.principal_v2.tail_latency_slo_budget_oa'
generate = make_lp_v2('security', 30)
