"""analyst.api_contract_payload.senior_fwd_k5 — mcq_concept (Senior). Суточный трафик интеграционного API-контракта между системами — прямой расчёт с учётом: шапка документа, события статусов, идемпотентные повторы, сжатие gzip, сверка реестров.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«api_contract_payload» в families/_w2010_scale_cat_analyst.py, ступень 5 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "analyst.api_contract_payload.senior_fwd_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
