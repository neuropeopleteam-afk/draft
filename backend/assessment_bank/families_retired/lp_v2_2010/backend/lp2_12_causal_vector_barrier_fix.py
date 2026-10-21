"""backend.principal_v2.causal_vector_barrier_fix — choose_fix (principal). Backend-разработка: Проверка причинной готовности сообщения по векторным часам от всех узлов.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'backend.principal_v2.causal_vector_barrier_fix'
generate = make_lp_v2('backend', 12)
