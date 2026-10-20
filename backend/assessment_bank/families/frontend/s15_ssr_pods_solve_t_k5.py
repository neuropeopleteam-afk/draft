"""frontend.ssr_pods.principal_solve_t_k5 — mcq_concept (Principal). Число подов SSR-рендеринга за CDN — обратная задача: наибольший допустимый вход «CPU на рендер страницы, мс» с учётом: кэш CDN, пиковый коэффициент, запас по загрузке, ядра на под, резерв на выкатку.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«ssr_pods» в families/_w2010_scale_cat_frontend.py, ступень 5 из 5, обратная задача по «t»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "frontend.ssr_pods.principal_solve_t_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
