"""frontend.lead_v2.multi_region_active_active_oa — open_answer (lead). Frontend-разработка: Архитектурный выбор: перевод контура в геораспределённый режим Active-Active.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'frontend.lead_v2.multi_region_active_active_oa'
generate = make_lp_v2('frontend', 28)
