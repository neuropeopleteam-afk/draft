"""common.cloud_cost.junior_fwd_k3 — mcq_concept (Junior). Месячный счёт за облачные виртуальные машины — прямой расчёт с учётом: скидка, диски и трафик, рост парка.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«cloud_cost» в families/_w2010_scale_cat_common.py, ступень 3 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "common.cloud_cost.junior_fwd_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
