"""backend.lead_v2.consistent_ring_wrap_fix — choose_fix (lead). Backend-разработка: Замыкание кольца консистентного хэширования с пропуском выведенных узлов.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'backend.lead_v2.consistent_ring_wrap_fix'
generate = make_lp_v2('backend', 8)
