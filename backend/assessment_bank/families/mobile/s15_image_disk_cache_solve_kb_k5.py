"""mobile.image_disk_cache.principal_solve_kb_k5 — mcq_concept (Senior). Объём дискового кэша изображений мобильного приложения — обратная задача: наибольший допустимый вход «средний размер превью, КБ» с учётом: сжатие AVIF/WebP, число сессий, плотность 3x, метаданные LRU, предзагрузка статики.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«image_disk_cache» в families/_w2010_scale_cat_mobile.py, ступень 5 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'mobile.image_disk_cache.principal_solve_kb_k5'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
