"""qa.principal_v2.p2c_latency_ewma_dispatch_out — predict_output (principal). Обеспечение качества (QA): Балансировка по эффективной цене узла (активные запросы × штраф латентности).

Волна LP-v2: содержательное семейство старших грейдов (проверка исполнением и рубрикой).
"""
from assessment_bank.families._lp_v2_defs import make_lp_v2

FAMILY_ID = 'qa.principal_v2.p2c_latency_ewma_dispatch_out'
generate = make_lp_v2('qa', 18)
