"""data_eng.lead_v2.retry_storm_amplification_inc — incident_sim (lead). Инженерия данных: Инцидент: каскадный шторм повторов между слоями без бюджета ретраев.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'data_eng.lead_v2.retry_storm_amplification_inc'
generate = make_lp_v2('data_eng', 25)
