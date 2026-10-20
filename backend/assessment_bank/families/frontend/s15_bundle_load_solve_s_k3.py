"""frontend.bundle_load.middle_solve_s_k3 — mcq_concept (Middle). Время загрузки и разбора JS-бандла первого экрана — обратная задача: наибольший допустимый вход «размер сжатого бандла, КБ» с учётом: code splitting, разбор и компиляция, сетевые RTT.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«bundle_load» в families/_w2010_scale_cat_frontend.py, ступень 3 из 5, обратная задача по «s»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "frontend.bundle_load.middle_solve_s_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
