"""mobile.lead_v2.quorum_ack_dedup_bug — find_bug (lead). Мобильная разработка: Ложный кворум из-за подсчёта повторных подтверждений от одного узла.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'mobile.lead_v2.quorum_ack_dedup_bug'
generate = make_lp_v2('mobile', 2)
