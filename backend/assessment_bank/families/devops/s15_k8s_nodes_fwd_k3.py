"""devops.k8s_nodes.junior_fwd_k3 — mcq_concept (Junior). Число узлов Kubernetes под requests подов — прямой расчёт с учётом: размер узла, системный резерв, запас по узлам.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«k8s_nodes» в families/_w2010_scale_cat_devops.py, ступень 3 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "devops.k8s_nodes.junior_fwd_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
