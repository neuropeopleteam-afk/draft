"""mobile.bundle_ota_size.middle_solve_res_k3 — mcq_concept (Middle). Размер установочного пакета и ресурсов мобильного релиза — обратная задача: наибольший допустимый вход «исходный объём ресурсов, МБ» с учётом: оптимизация R8/Stripping, сплит App Bundle, локальные ML-модели.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«bundle_ota_size» в families/_w2010_scale_cat_mobile.py, ступень 3 из 5, обратная задача по «res»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "mobile.bundle_ota_size.middle_solve_res_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
