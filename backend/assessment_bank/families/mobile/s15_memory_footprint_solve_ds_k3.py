"""mobile.memory_footprint.senior_solve_ds_k3 — mcq_concept (Senior). Пиковое потребление оперативной памяти (RAM) мобильным экраном — обратная задача: наименьший допустимый вход «экономия от даунсэмплинга, %» с учётом: даунсэмплинг битмапов, дерево View и замыкания, буферы JSON.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«memory_footprint» в families/_w2010_scale_cat_mobile.py, ступень 3 из 5, обратная задача по «ds»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "mobile.memory_footprint.senior_solve_ds_k3"
N_ABOVE = (1, 2)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
