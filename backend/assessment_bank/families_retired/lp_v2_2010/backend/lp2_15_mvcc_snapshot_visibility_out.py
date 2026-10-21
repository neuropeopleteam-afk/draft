"""backend.lead_v2.mvcc_snapshot_visibility_out — predict_output (lead). Backend-разработка: Видимость версий строк при чтении снимка MVCC с активными транзакциями.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'backend.lead_v2.mvcc_snapshot_visibility_out'
generate = make_lp_v2('backend', 15)
