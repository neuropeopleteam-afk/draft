"""frontend.frame_budget.principal_solve_br_k5 — mcq_concept (Senior). Сколько элементов можно анимировать в бюджете кадра — обратная задача: наибольший допустимый вход «работа браузера в кадре, мс» с учётом: работа браузера, запас кадра, слабые устройства, скрипт аналитики, постоянные элементы.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«frame_budget» в families/_w2010_scale_cat_frontend.py, ступень 5 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'frontend.frame_budget.principal_solve_br_k5'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
