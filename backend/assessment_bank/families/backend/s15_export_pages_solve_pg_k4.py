"""backend.export_pages.senior_solve_pg_k4 — mcq_concept (Senior). Время постраничной выгрузки из API/БД — обратная задача: наибольший допустимый вход «число страниц» с учётом: параллельные воркеры, запись в приёмник, перечитывание страниц, замедление БД днём.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«export_pages» в families/_w2010_scale_cat_backend.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'backend.export_pages.senior_solve_pg_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
