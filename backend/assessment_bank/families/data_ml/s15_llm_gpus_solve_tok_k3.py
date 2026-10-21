"""data_ml.llm_gpus.senior_solve_tok_k3 — mcq_concept (Senior). Число GPU для инференса LLM по токенам в секунду — обратная задача: наибольший допустимый вход «средняя длина ответа, токенов» с учётом: производительность GPU, пиковый коэффициент, запас загрузки GPU.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«llm_gpus» в families/_w2010_scale_cat_data_ml.py, ступень 3 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'data_ml.llm_gpus.senior_solve_tok_k3'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
