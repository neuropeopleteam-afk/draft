"""devops.k8s_nodes.senior_solve_nc_k3 — mcq_concept (Senior). Число узлов Kubernetes под requests подов — обратная задача: наименьший допустимый вход «размер узла, vCPU» с учётом: размер узла, системный резерв, запас по узлам.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«k8s_nodes» в families/_w2010_scale_cat_devops.py, ступень 3 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'devops.k8s_nodes.senior_solve_nc_k3'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
