"""mobile.image_disk_cache.middle_solve_kb_k2 — mcq_concept (Middle). Объём дискового кэша изображений мобильного приложения — обратная задача: наибольший допустимый вход «средний размер превью, КБ» с учётом: сжатие AVIF/WebP, число сессий.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«image_disk_cache» в families/_w2010_scale_cat_mobile.py, ступень 2 из 5, обратная задача по «kb»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "mobile.image_disk_cache.middle_solve_kb_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
