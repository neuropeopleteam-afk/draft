"""data_ml.lead_v2.capped_backoff_budget_fix — choose_fix (senior, lead). Аналитика данных и ML: Ограничение экспоненциальной паузы повторов с контролем общего дедлайна.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'data_ml.lead_v2.capped_backoff_budget_fix'
generate = make_lp_v2('data_ml', 7)
