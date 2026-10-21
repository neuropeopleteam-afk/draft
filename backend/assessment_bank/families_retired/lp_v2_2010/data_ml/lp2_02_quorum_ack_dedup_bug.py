"""data_ml.lead_v2.quorum_ack_dedup_bug — find_bug (lead). Аналитика данных и ML: Ложный кворум из-за подсчёта повторных подтверждений от одного узла.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'data_ml.lead_v2.quorum_ack_dedup_bug'
generate = make_lp_v2('data_ml', 2)
