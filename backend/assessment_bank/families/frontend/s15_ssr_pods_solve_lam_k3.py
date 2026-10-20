"""frontend.ssr_pods.middle_solve_lam_k3 — mcq_concept (Middle). Число подов SSR-рендеринга за CDN — обратная задача: наибольший допустимый вход «поток страниц в секунду» с учётом: кэш CDN, пиковый коэффициент, запас по загрузке.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«ssr_pods» в families/_w2010_scale_cat_frontend.py, ступень 3 из 5, обратная задача по «lam»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "frontend.ssr_pods.middle_solve_lam_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
