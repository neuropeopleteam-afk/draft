"""common.backup_window.senior_solve_v_k4 — mcq_concept (Lead). Длительность резервного копирования в окне обслуживания — обратная задача: наибольший допустимый вход «объём данных, ГБ» с учётом: инкрементальная копия, сжатие, проверка контрольных сумм, параллельные потоки.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«backup_window» в families/_w2010_scale_cat_common.py, ступень 4 из 5, обратная задача по «V»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "common.backup_window.senior_solve_v_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
