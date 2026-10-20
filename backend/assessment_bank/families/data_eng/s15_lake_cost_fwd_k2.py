"""data_eng.lake_cost.intern_fwd_k2 — mcq_concept (Стажёр). Месячная стоимость хранения озера данных в S3 — прямой расчёт с учётом: сжатие, холодный класс.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«lake_cost» в families/_w2010_scale_cat_data_eng.py, ступень 2 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_eng.lake_cost.intern_fwd_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
