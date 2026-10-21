"""security.lead_v2.zero_downtime_contract_mig_oa — open_answer (lead). Информационная безопасность: План миграции схемы и контрактов под нагрузкой без окна простоя (Expand-Contract).

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'security.lead_v2.zero_downtime_contract_mig_oa'
generate = make_lp_v2('security', 29)
