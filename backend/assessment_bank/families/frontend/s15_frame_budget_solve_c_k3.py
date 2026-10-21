"""frontend.frame_budget.middle_solve_c_k3 — mcq_concept (Middle). Сколько элементов можно анимировать в бюджете кадра — обратная задача: наибольший допустимый вход «стоимость обновления элемента, мкс» с учётом: работа браузера, запас кадра, слабые устройства.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«frame_budget» в families/_w2010_scale_cat_frontend.py, ступень 3 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'frontend.frame_budget.middle_solve_c_k3'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
