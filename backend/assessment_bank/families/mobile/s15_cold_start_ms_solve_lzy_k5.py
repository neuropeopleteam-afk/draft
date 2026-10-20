"""mobile.cold_start_ms.principal_solve_lzy_k5 — mcq_concept (Principal). Бюджет времени холодного старта мобильного приложения — обратная задача: наименьший допустимый вход «доля отложенной инициализации, %» с учётом: ленивая инициализация, параллельный пул, работа с Keystore, первый кадр UI, создание процесса.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«cold_start_ms» в families/_w2010_scale_cat_mobile.py, ступень 5 из 5, обратная задача по «lzy»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "mobile.cold_start_ms.principal_solve_lzy_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
