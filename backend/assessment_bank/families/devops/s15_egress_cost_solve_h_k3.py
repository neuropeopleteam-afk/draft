"""devops.egress_cost.senior_solve_h_k3 — mcq_concept (Senior). Стоимость исходящего трафика и CDN — обратная задача: наименьший допустимый вход «доля трафика через CDN, %» с учётом: доля CDN, докачки, сжатие.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«egress_cost» в families/_w2010_scale_cat_devops.py, ступень 3 из 5, обратная задача по «h»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "devops.egress_cost.senior_solve_h_k3"
N_ABOVE = (2,)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
