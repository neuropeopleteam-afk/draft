"""qa.bug_backlog.junior_solve_bl_k2 — mcq_concept (Junior). Через сколько дней будет разобран бэклог багов — обратная задача: наибольший допустимый вход «открытых багов» с учётом: дубликаты, переоткрытия.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«bug_backlog» в families/_w2010_scale_cat_qa.py, ступень 2 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'qa.bug_backlog.junior_solve_bl_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
