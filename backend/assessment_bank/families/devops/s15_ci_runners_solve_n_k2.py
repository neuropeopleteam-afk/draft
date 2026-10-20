"""devops.ci_runners.junior_solve_n_k2 — mcq_concept (Junior). Число CI-раннеров под поток пайплайнов — обратная задача: наибольший допустимый вход «пайплайнов в час» с учётом: пиковый коэффициент, перезапуски флаки.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«ci_runners» в families/_w2010_scale_cat_devops.py, ступень 2 из 5, обратная задача по «n»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "devops.ci_runners.junior_solve_n_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
