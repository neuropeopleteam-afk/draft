"""data_ml.principal_v2.hierarchical_tenant_quota_fix — choose_fix (principal). Аналитика данных и ML: Двухуровневое квотирование: лимит тенанта и защищённый резерв критичного трафика.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'data_ml.principal_v2.hierarchical_tenant_quota_fix'
generate = make_lp_v2('data_ml', 13)
