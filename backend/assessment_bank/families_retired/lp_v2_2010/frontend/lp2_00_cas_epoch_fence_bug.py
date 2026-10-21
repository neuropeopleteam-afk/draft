"""frontend.lead_v2.cas_epoch_fence_bug — find_bug (senior, lead). Frontend-разработка: Потеря монотонности fencing-токена при оптимистичной записи.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'frontend.lead_v2.cas_epoch_fence_bug'
generate = make_lp_v2('frontend', 0)
