"""qa.coverage_effort.middle_solve_cov_k2 — mcq_concept (Middle). Трудозатраты на рост покрытия тестами — обратная задача: наименьший допустимый вход «текущее покрытие, %» с учётом: строки на тест, темп написания.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«coverage_effort» в families/_w2010_scale_cat_qa.py, ступень 2 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'qa.coverage_effort.middle_solve_cov_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
