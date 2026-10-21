"""devops.ci_runners.middle_solve_n_k3 — mcq_concept (Middle). Число CI-раннеров под поток пайплайнов — обратная задача: наибольший допустимый вход «пайплайнов в час» с учётом: пиковый коэффициент, перезапуски флаки, кэш зависимостей.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«ci_runners» в families/_w2010_scale_cat_devops.py, ступень 3 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'devops.ci_runners.middle_solve_n_k3'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
