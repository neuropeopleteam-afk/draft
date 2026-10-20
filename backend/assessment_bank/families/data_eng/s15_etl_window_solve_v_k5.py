"""data_eng.etl_window.principal_solve_v_k5 — mcq_concept (Principal). Длительность ночного ETL-окна — обратная задача: наименьший допустимый вход «скорость одного потока, МБ/с» с учётом: потоки, трансформации, перезапуски, рост данных, проверки качества.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«etl_window» в families/_w2010_scale_cat_data_eng.py, ступень 5 из 5, обратная задача по «v»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_eng.etl_window.principal_solve_v_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
