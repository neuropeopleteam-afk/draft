"""mobile.lead_v2.pool_starvation_cascade_inc — incident_sim (senior, lead). Мобильная разработка: Инцидент: исчерпание пула соединений из-за внешнего вызова внутри транзакции.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'mobile.lead_v2.pool_starvation_cascade_inc'
generate = make_lp_v2('mobile', 24)
