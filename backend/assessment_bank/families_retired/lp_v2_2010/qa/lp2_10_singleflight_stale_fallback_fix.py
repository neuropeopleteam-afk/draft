"""qa.principal_v2.singleflight_stale_fallback_fix — choose_fix (lead, principal). Обеспечение качества (QA): Подавление шторма пересчёта кэша с возвратом устаревшего значения при сбое.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'qa.principal_v2.singleflight_stale_fallback_fix'
generate = make_lp_v2('qa', 10)
