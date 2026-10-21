"""mobile.lead_v2.capped_backoff_budget_fix — choose_fix (senior, lead). Мобильная разработка: Ограничение экспоненциальной паузы повторов с контролем общего дедлайна.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'mobile.lead_v2.capped_backoff_budget_fix'
generate = make_lp_v2('mobile', 7)
