"""backend.export_pages.middle_fwd_k4 — mcq_concept (Middle). Время постраничной выгрузки из API/БД — прямой расчёт с учётом: параллельные воркеры, запись в приёмник, перечитывание страниц, замедление БД днём.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«export_pages» в families/_w2010_scale_cat_backend.py, ступень 4 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'backend.export_pages.middle_fwd_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
