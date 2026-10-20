"""analyst.api_contract_payload.junior_solve_ord_k2 — mcq_concept (Junior). Суточный трафик интеграционного API-контракта между системами — обратная задача: наибольший допустимый вход «документов в сутки, тыс.» с учётом: шапка документа, события статусов.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«api_contract_payload» в families/_w2010_scale_cat_analyst.py, ступень 2 из 5, обратная задача по «ord»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "analyst.api_contract_payload.junior_solve_ord_k2"
N_ABOVE = (1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
