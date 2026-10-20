"""data_ml.llm_gpus.intern_fwd_k2 — mcq_concept (Стажёр). Число GPU для инференса LLM по токенам в секунду — прямой расчёт с учётом: производительность GPU, пиковый коэффициент.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«llm_gpus» в families/_w2010_scale_cat_data_ml.py, ступень 2 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_ml.llm_gpus.intern_fwd_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
