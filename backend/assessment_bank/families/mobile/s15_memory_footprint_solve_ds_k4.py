"""mobile.memory_footprint.lead_solve_ds_k4 — mcq_concept (Middle). Пиковое потребление оперативной памяти (RAM) мобильным экраном — обратная задача: наименьший допустимый вход «экономия от даунсэмплинга, %» с учётом: даунсэмплинг битмапов, дерево View и замыкания, буферы JSON, фрагментация кучи.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«memory_footprint» в families/_w2010_scale_cat_mobile.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'mobile.memory_footprint.lead_solve_ds_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
