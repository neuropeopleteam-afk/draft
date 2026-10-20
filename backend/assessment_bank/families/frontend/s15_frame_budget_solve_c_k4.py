"""frontend.frame_budget.senior_solve_c_k4 — mcq_concept (Lead). Сколько элементов можно анимировать в бюджете кадра — обратная задача: наибольший допустимый вход «стоимость обновления элемента, мкс» с учётом: работа браузера, запас кадра, слабые устройства, скрипт аналитики.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«frame_budget» в families/_w2010_scale_cat_frontend.py, ступень 4 из 5, обратная задача по «c»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "frontend.frame_budget.senior_solve_c_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
