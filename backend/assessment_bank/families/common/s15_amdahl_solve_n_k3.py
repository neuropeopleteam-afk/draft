"""common.amdahl.middle_solve_n_k3 — mcq_concept (Middle). Время задачи на нескольких ядрах по закону Амдала — обратная задача: наименьший допустимый вход «число ядер» с учётом: накладные расходы синхронизации, запуск, тротлинг CPU.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«amdahl» в families/_w2010_scale_cat_common.py, ступень 3 из 5, обратная задача по «n»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "common.amdahl.middle_solve_n_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
