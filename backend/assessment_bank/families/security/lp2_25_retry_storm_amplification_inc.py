"""security.lead_v2.retry_storm_amplification_inc — incident_sim (lead). Информационная безопасность: Инцидент: каскадный шторм повторов между слоями без бюджета ретраев.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'security.lead_v2.retry_storm_amplification_inc'
generate = make_lp_v2('security', 25)
