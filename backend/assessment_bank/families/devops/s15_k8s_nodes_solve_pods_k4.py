"""devops.k8s_nodes.senior_solve_pods_k4 — mcq_concept (Lead). Число узлов Kubernetes под requests подов — обратная задача: наибольший допустимый вход «число подов» с учётом: размер узла, системный резерв, запас по узлам, рост.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«k8s_nodes» в families/_w2010_scale_cat_devops.py, ступень 4 из 5, обратная задача по «pods»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "devops.k8s_nodes.senior_solve_pods_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
