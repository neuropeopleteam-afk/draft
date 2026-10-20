"""data_ml.rag_cost.lead_solve_nq_k5 — mcq_concept (Principal). Суточная стоимость RAG-ассистента на LLM API — обратная задача: наибольший допустимый вход «запросов в сутки, тыс.» с учётом: системный промпт, цена токенов, выходные токены, кэш промптов, эмбеддинги.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«rag_cost» в families/_w2010_scale_cat_data_ml.py, ступень 5 из 5, обратная задача по «nq»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_ml.rag_cost.lead_solve_nq_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
