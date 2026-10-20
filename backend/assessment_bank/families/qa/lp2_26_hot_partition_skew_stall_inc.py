"""qa.principal_v2.hot_partition_skew_stall_inc — incident_sim (lead, principal). Обеспечение качества (QA): Инцидент: деградация p99 из-за перекоса горячего ключа и блокировки очереди.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'qa.principal_v2.hot_partition_skew_stall_inc'
generate = make_lp_v2('qa', 26)
