"""data_eng.dq.dq_sigma_threshold_mcq — mcq_concept (Senior/Lead). Качество данных: порог аномалии mean + kσ — генеральное отклонение против выборочного.

Модель предметной области, ловушки и тексты — в families/_w2010_defs*.py (DEFS["data_eng.dq.dq_sigma_threshold_mcq"]);
генерация и проверки исполнением — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_defs import make

FAMILY_ID = "data_eng.dq.dq_sigma_threshold_mcq"
generate = make(FAMILY_ID)
