"""mobile.location_battery.senior_solve_f_k4 — mcq_concept (Lead). Расход заряда батареи фоновым трекингом геолокации — обратная задача: наибольший допустимый вход «опросов геолокации в час» с учётом: отключение на стоянках, радиоканал LTE, расчёт геозон, пакетирование сети.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«location_battery» в families/_w2010_scale_cat_mobile.py, ступень 4 из 5, обратная задача по «f»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "mobile.location_battery.senior_solve_f_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
