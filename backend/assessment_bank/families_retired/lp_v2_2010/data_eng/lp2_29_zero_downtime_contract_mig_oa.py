"""data_eng.lead_v2.zero_downtime_contract_mig_oa — open_answer (lead). Инженерия данных: План миграции схемы и контрактов под нагрузкой без окна простоя (Expand-Contract).

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'data_eng.lead_v2.zero_downtime_contract_mig_oa'
generate = make_lp_v2('data_eng', 29)
