"""qa.bug_backlog.junior_fwd_k3 — mcq_concept (Junior). Через сколько дней будет разобран бэклог багов — прямой расчёт с учётом: дубликаты, переоткрытия, праздники.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«bug_backlog» в families/_w2010_scale_cat_qa.py, ступень 3 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "qa.bug_backlog.junior_fwd_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
