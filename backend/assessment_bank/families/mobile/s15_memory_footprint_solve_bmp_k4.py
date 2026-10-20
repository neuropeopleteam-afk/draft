"""mobile.memory_footprint.senior_solve_bmp_k4 — mcq_concept (Lead). Пиковое потребление оперативной памяти (RAM) мобильным экраном — обратная задача: наибольший допустимый вход «число одновременно декодированных битмапов» с учётом: даунсэмплинг битмапов, дерево View и замыкания, буферы JSON, фрагментация кучи.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«memory_footprint» в families/_w2010_scale_cat_mobile.py, ступень 4 из 5, обратная задача по «bmp»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "mobile.memory_footprint.senior_solve_bmp_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
