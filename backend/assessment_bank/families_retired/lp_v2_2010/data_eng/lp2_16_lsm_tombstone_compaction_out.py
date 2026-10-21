"""data_eng.lead_v2.lsm_tombstone_compaction_out — predict_output (lead). Инженерия данных: Слияние уровней LSM-дерева с удержанием маркеров удаления до горизонта снимка.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'data_eng.lead_v2.lsm_tombstone_compaction_out'
generate = make_lp_v2('data_eng', 16)
