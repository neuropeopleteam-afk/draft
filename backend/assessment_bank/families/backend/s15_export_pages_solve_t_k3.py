"""backend.export_pages.senior_solve_t_k3 — mcq_concept (Senior). Время постраничной выгрузки из API/БД — обратная задача: наибольший допустимый вход «время запроса одной страницы, мс» с учётом: параллельные воркеры, запись в приёмник, перечитывание страниц.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«export_pages» в families/_w2010_scale_cat_backend.py, ступень 3 из 5, обратная задача по «t»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "backend.export_pages.senior_solve_t_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
