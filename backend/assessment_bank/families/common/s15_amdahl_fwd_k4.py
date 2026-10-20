"""common.amdahl.middle_fwd_k4 — mcq_concept (Middle). Время задачи на нескольких ядрах по закону Амдала — прямой расчёт с учётом: накладные расходы синхронизации, запуск, тротлинг CPU, задачи в пакете.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«amdahl» в families/_w2010_scale_cat_common.py, ступень 4 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "common.amdahl.middle_fwd_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
