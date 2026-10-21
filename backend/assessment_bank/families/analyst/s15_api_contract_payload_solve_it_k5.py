"""analyst.api_contract_payload.principal_solve_it_k5 — mcq_concept (Senior). Суточный трафик интеграционного API-контракта между системами — обратная задача: наибольший допустимый вход «среднее число позиций в документе» с учётом: шапка документа, события статусов, идемпотентные повторы, сжатие gzip, сверка реестров.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«api_contract_payload» в families/_w2010_scale_cat_analyst.py, ступень 5 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'analyst.api_contract_payload.principal_solve_it_k5'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
