"""frontend.frame_budget.junior_fwd_k3 — mcq_concept (Junior). Сколько элементов можно анимировать в бюджете кадра — прямой расчёт с учётом: работа браузера, запас кадра, слабые устройства.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«frame_budget» в families/_w2010_scale_cat_frontend.py, ступень 3 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "frontend.frame_budget.junior_fwd_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
