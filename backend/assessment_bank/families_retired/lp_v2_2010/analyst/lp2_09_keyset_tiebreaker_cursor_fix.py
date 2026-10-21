"""analyst.lead_v2.keyset_tiebreaker_cursor_fix — choose_fix (lead). Системный и бизнес-анализ: Курсорная пагинация без потери записей с совпадающей меткой времени.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'analyst.lead_v2.keyset_tiebreaker_cursor_fix'
generate = make_lp_v2('analyst', 9)
