"""qa.bug_backlog.senior_solve_bl_k4 — mcq_concept (Lead). Через сколько дней будет разобран бэклог багов — обратная задача: наибольший допустимый вход «открытых багов» с учётом: дубликаты, переоткрытия, праздники, автотриаж.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«bug_backlog» в families/_w2010_scale_cat_qa.py, ступень 4 из 5, обратная задача по «bl»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "qa.bug_backlog.senior_solve_bl_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
