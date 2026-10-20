"""devops.ci_runners.middle_solve_t_k2 — mcq_concept (Middle). Число CI-раннеров под поток пайплайнов — обратная задача: наибольший допустимый вход «длительность джобы, мин» с учётом: пиковый коэффициент, перезапуски флаки.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«ci_runners» в families/_w2010_scale_cat_devops.py, ступень 2 из 5, обратная задача по «t»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "devops.ci_runners.middle_solve_t_k2"
N_ABOVE = (1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
