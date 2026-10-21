"""data_eng.dwh_scan.middle_fwd_k4 — mcq_concept (Middle). Стоимость сканирования данных в облачном DWH — прямой расчёт с учётом: колоночное чтение, отсечение партиций, кэш результатов, период.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«dwh_scan» в families/_w2010_scale_cat_data_eng.py, ступень 4 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'data_eng.dwh_scan.middle_fwd_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
