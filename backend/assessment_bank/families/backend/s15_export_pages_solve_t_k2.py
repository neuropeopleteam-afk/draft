"""backend.export_pages.middle_solve_t_k2 — mcq_concept (Middle). Время постраничной выгрузки из API/БД — обратная задача: наибольший допустимый вход «время запроса одной страницы, мс» с учётом: параллельные воркеры, запись в приёмник.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«export_pages» в families/_w2010_scale_cat_backend.py, ступень 2 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'backend.export_pages.middle_solve_t_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
