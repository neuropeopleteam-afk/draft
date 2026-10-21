"""qa.lead_v2.dual_write_outbox_drift_ob3 — open_book_3step (lead). Обеспечение качества (QA): Развал консистентности при двойной записи в БД и брокер без outbox (3 шага).

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'qa.lead_v2.dual_write_outbox_drift_ob3'
generate = make_lp_v2('qa', 21)
