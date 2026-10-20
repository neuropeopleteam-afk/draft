"""common.backup_window.middle_solve_sp_k2 — mcq_concept (Middle). Длительность резервного копирования в окне обслуживания — обратная задача: наименьший допустимый вход «скорость копирования, МБ/с» с учётом: инкрементальная копия, сжатие.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«backup_window» в families/_w2010_scale_cat_common.py, ступень 2 из 5, обратная задача по «sp»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "common.backup_window.middle_solve_sp_k2"
N_ABOVE = (1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
