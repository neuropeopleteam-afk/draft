"""data_eng.lead_v2.token_bucket_refill_trace_out — predict_output (senior, lead). Инженерия данных: Трассировка корзины токенов с дробным пополнением и потолком всплеска.

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'data_eng.lead_v2.token_bucket_refill_trace_out'
generate = make_lp_v2('data_eng', 14)
