"""devops.egress_cost.lead_solve_mau_k5 — mcq_concept (Senior). Стоимость исходящего трафика и CDN — обратная задача: наибольший допустимый вход «активных пользователей, тыс.» с учётом: доля CDN, докачки, сжатие, НДС, абонентская плата.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«egress_cost» в families/_w2010_scale_cat_devops.py, ступень 5 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'devops.egress_cost.lead_solve_mau_k5'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
