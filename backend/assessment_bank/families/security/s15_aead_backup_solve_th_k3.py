"""security.aead_backup.senior_solve_th_k3 — mcq_concept (Senior). Длительность шифрования и выгрузки резервной копии — обратная задача: наименьший допустимый вход «число потоков шифрования» с учётом: сжатие, потоки шифрования, проверка тегов.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«aead_backup» в families/_w2010_scale_cat_security.py, ступень 3 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'security.aead_backup.senior_solve_th_k3'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
