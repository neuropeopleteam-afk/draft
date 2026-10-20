"""data_ml.vram_fit.middle_solve_bs_k2 — mcq_concept (Middle). Память GPU под веса LLM и KV-кэш — обратная задача: наибольший допустимый вход «число одновременных запросов» с учётом: KV-кэш, активации.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«vram_fit» в families/_w2010_scale_cat_data_ml.py, ступень 2 из 5, обратная задача по «bs»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_ml.vram_fit.middle_solve_bs_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
