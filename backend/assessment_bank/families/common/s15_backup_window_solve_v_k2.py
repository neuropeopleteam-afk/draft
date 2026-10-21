"""common.backup_window.junior_solve_v_k2 — mcq_concept (Junior). Длительность резервного копирования в окне обслуживания — обратная задача: наибольший допустимый вход «объём данных, ГБ» с учётом: инкрементальная копия, сжатие.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«backup_window» в families/_w2010_scale_cat_common.py, ступень 2 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'common.backup_window.junior_solve_v_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
