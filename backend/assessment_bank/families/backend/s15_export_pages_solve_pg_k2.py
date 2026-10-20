"""backend.export_pages.junior_solve_pg_k2 — mcq_concept (Junior). Время постраничной выгрузки из API/БД — обратная задача: наибольший допустимый вход «число страниц» с учётом: параллельные воркеры, запись в приёмник.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«export_pages» в families/_w2010_scale_cat_backend.py, ступень 2 из 5, обратная задача по «pg»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "backend.export_pages.junior_solve_pg_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
