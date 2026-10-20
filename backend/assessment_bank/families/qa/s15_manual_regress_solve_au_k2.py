"""qa.manual_regress.middle_solve_au_k2 — mcq_concept (Middle). Длительность ручного регресса перед релизом — обратная задача: наименьший допустимый вход «доля автоматизации, %» с учётом: автоматизация, тестировщики.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«manual_regress» в families/_w2010_scale_cat_qa.py, ступень 2 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'qa.manual_regress.middle_solve_au_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
