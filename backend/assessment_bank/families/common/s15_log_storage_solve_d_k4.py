"""common.log_storage.lead_solve_d_k4 — mcq_concept (Middle). Объём хранилища логов с учётом срока хранения и реплик — обратная задача: наибольший допустимый вход «срок хранения в днях» с учётом: срок хранения, сжатие, число копий, служебные структуры.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«log_storage» в families/_w2010_scale_cat_common.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'common.log_storage.lead_solve_d_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
