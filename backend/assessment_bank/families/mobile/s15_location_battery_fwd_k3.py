"""mobile.location_battery.junior_fwd_k3 — mcq_concept (Junior). Расход заряда батареи фоновым трекингом геолокации — прямой расчёт с учётом: отключение на стоянках, радиоканал LTE, расчёт геозон.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«location_battery» в families/_w2010_scale_cat_mobile.py, ступень 3 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'mobile.location_battery.junior_fwd_k3'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
