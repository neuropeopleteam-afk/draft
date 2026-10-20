"""mobile.image_disk_cache.senior_solve_scr_k4 — mcq_concept (Lead). Объём дискового кэша изображений мобильного приложения — обратная задача: наибольший допустимый вход «экранов за сессию» с учётом: сжатие AVIF/WebP, число сессий, плотность 3x, метаданные LRU.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«image_disk_cache» в families/_w2010_scale_cat_mobile.py, ступень 4 из 5, обратная задача по «scr»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "mobile.image_disk_cache.senior_solve_scr_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
