"""backend.principal_v2.stale_cache_poison_rollout_inc — incident_sim (principal). Backend-разработка: Инцидент: отравление общего кэша несовместимой схемой при канарской выкладке.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'backend.principal_v2.stale_cache_poison_rollout_inc'
generate = make_lp_v2('backend', 27)
