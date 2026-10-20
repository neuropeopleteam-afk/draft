"""data_ml.rag_cost.senior_fwd_k5 — mcq_concept (Senior). Суточная стоимость RAG-ассистента на LLM API — прямой расчёт с учётом: системный промпт, цена токенов, выходные токены, кэш промптов, эмбеддинги.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«rag_cost» в families/_w2010_scale_cat_data_ml.py, ступень 5 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_ml.rag_cost.senior_fwd_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
