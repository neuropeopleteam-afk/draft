"""data_ml.principal_v2.stale_cache_poison_rollout_inc — incident_sim (principal). Аналитика данных и ML: Инцидент: отравление общего кэша несовместимой схемой при канарской выкладке.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'data_ml.principal_v2.stale_cache_poison_rollout_inc'
generate = make_lp_v2('data_ml', 27)
