"""devops.ci_runners.lead_solve_t_k4 — mcq_concept (Middle). Число CI-раннеров под поток пайплайнов — обратная задача: наибольший допустимый вход «длительность джобы, мин» с учётом: пиковый коэффициент, перезапуски флаки, кэш зависимостей, запас раннеров.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«ci_runners» в families/_w2010_scale_cat_devops.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'devops.ci_runners.lead_solve_t_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
