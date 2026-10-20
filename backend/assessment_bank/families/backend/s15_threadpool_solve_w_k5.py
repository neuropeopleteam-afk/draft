"""backend.threadpool.lead_solve_w_k5 — mcq_concept (Principal). Размер пула потоков по формуле Гётца (CPU + ожидание) — обратная задача: наибольший допустимый вход «время ожидания внешних вызовов, мс» с учётом: пиковое ожидание, целевая загрузка CPU, ядра под GC и систему, запас на рост, служебные потоки.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«threadpool» в families/_w2010_scale_cat_backend.py, ступень 5 из 5, обратная задача по «w»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "backend.threadpool.lead_solve_w_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
