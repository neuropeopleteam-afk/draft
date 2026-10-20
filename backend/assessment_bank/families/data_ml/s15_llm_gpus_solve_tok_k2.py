"""data_ml.llm_gpus.middle_solve_tok_k2 — mcq_concept (Middle). Число GPU для инференса LLM по токенам в секунду — обратная задача: наибольший допустимый вход «средняя длина ответа, токенов» с учётом: производительность GPU, пиковый коэффициент.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«llm_gpus» в families/_w2010_scale_cat_data_ml.py, ступень 2 из 5, обратная задача по «tok»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_ml.llm_gpus.middle_solve_tok_k2"
N_ABOVE = (1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
