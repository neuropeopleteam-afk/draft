"""analyst.lead_v2.sliding_budget_evict_bug — find_bug (senior, lead). Системный и бизнес-анализ: Утечка веса при вытеснении устаревших событий из скользящего окна.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'analyst.lead_v2.sliding_budget_evict_bug'
generate = make_lp_v2('analyst', 1)
