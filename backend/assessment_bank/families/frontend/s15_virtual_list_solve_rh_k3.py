"""frontend.virtual_list.senior_solve_rh_k3 — mcq_concept (Senior). Число DOM-узлов виртуализированного списка — обратная задача: наименьший допустимый вход «высота строки, px» с учётом: overscan, ячейки в строке, узлы в ячейке.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«virtual_list» в families/_w2010_scale_cat_frontend.py, ступень 3 из 5, обратная задача по «rh»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "frontend.virtual_list.senior_solve_rh_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
