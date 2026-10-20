"""mobile.frame_jank_budget.principal_solve_us_k5 — mcq_concept (Principal). Нагрузка главного потока UI при прокрутке сложной ленты — обратная задача: наибольший допустимый вход «время привязки одного элемента, мкс» с учётом: мемоизация состояния, фоновый парсинг, сложные тени, анимации переходов, системный обход.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«frame_jank_budget» в families/_w2010_scale_cat_mobile.py, ступень 5 из 5, обратная задача по «us»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "mobile.frame_jank_budget.principal_solve_us_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
