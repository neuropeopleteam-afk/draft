"""common.principal_v2.read_repair_monotonic_ob3 — open_book_3step (principal). Общеинженерный контур: Немонотонное чтение при неполном кворуме и гонке read-repair (3 шага).

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'common.principal_v2.read_repair_monotonic_ob3'
generate = make_lp_v2('common', 22)
