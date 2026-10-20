"""data_ml.vram_fit.lead_solve_pb_k5 — mcq_concept (Principal). Память GPU под веса LLM и KV-кэш — обратная задача: наибольший допустимый вход «размер модели, млрд параметров» с учётом: KV-кэш, активации, tensor parallel, запас памяти, рантайм.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«vram_fit» в families/_w2010_scale_cat_data_ml.py, ступень 5 из 5, обратная задача по «pb»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_ml.vram_fit.lead_solve_pb_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
