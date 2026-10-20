"""mobile.cold_start_ms.senior_solve_mod_k4 — mcq_concept (Lead). Бюджет времени холодного старта мобильного приложения — обратная задача: наибольший допустимый вход «число модулей на старте» с учётом: ленивая инициализация, параллельный пул, работа с Keystore, первый кадр UI.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«cold_start_ms» в families/_w2010_scale_cat_mobile.py, ступень 4 из 5, обратная задача по «mod»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "mobile.cold_start_ms.senior_solve_mod_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
