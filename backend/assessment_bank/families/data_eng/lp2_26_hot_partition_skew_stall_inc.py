"""data_eng.principal_v2.hot_partition_skew_stall_inc — open_book_3step (lead, principal). Инженерия данных: Инцидент: деградация p99 из-за перекоса горячего ключа и блокировки очереди.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'data_eng.principal_v2.hot_partition_skew_stall_inc'
generate = make_lp_v2('data_eng', 26)
