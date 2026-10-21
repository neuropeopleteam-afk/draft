"""analyst.principal_v2.raft_election_quorum_out — predict_output (lead, principal). Системный и бизнес-анализ: Отбор лидера по актуальности журнала (term, длина) и подсчёт кворума голосов.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'analyst.principal_v2.raft_election_quorum_out'
generate = make_lp_v2('analyst', 17)
