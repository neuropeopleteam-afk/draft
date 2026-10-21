"""data_eng.lead_v2.pool_starvation_cascade_inc — open_book_3step (senior, lead). Инженерия данных: Инцидент: исчерпание пула соединений из-за внешнего вызова внутри транзакции.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'data_eng.lead_v2.pool_starvation_cascade_inc'
generate = make_lp_v2('data_eng', 24)
