"""qa.coverage_effort.senior_solve_loc_k4 — mcq_concept (Senior). Трудозатраты на рост покрытия тестами — обратная задача: наибольший допустимый вход «размер кода, тыс. строк» с учётом: строки на тест, темп написания, рост кода, ревью.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«coverage_effort» в families/_w2010_scale_cat_qa.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'qa.coverage_effort.senior_solve_loc_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
