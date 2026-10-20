"""mobile.location_battery.middle_solve_hr_k2 — mcq_concept (Middle). Расход заряда батареи фоновым трекингом геолокации — обратная задача: наибольший допустимый вход «длительность смены, ч» с учётом: отключение на стоянках, радиоканал LTE.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«location_battery» в families/_w2010_scale_cat_mobile.py, ступень 2 из 5, обратная задача по «hr»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "mobile.location_battery.middle_solve_hr_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
