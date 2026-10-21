"""backend.lead_v2.multi_region_active_active_oa — open_answer (lead). Backend-разработка: Архитектурный выбор: перевод контура в геораспределённый режим Active-Active.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'backend.lead_v2.multi_region_active_active_oa'
generate = make_lp_v2('backend', 28)
