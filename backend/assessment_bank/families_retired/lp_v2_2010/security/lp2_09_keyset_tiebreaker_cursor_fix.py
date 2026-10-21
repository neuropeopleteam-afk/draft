"""security.lead_v2.keyset_tiebreaker_cursor_fix — choose_fix (lead). Информационная безопасность: Курсорная пагинация без потери записей с совпадающей меткой времени.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'security.lead_v2.keyset_tiebreaker_cursor_fix'
generate = make_lp_v2('security', 9)
