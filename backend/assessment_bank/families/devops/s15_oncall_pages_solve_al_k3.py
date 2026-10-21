"""devops.oncall_pages.middle_solve_al_k3 — mcq_concept (Middle). Нагрузка дежурного по алертам — обратная задача: наибольший допустимый вход «число правил» с учётом: доля пейджей, группировка, чистка шума.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«oncall_pages» в families/_w2010_scale_cat_devops.py, ступень 3 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'devops.oncall_pages.middle_solve_al_k3'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
