"""mobile.memory_footprint.intern_fwd_k2 — mcq_concept (Стажёр). Пиковое потребление оперативной памяти (RAM) мобильным экраном — прямой расчёт с учётом: даунсэмплинг битмапов, дерево View и замыкания.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«memory_footprint» в families/_w2010_scale_cat_mobile.py, ступень 2 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "mobile.memory_footprint.intern_fwd_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
