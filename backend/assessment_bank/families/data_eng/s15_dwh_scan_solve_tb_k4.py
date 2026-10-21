"""data_eng.dwh_scan.senior_solve_tb_k4 — mcq_concept (Senior). Стоимость сканирования данных в облачном DWH — обратная задача: наибольший допустимый вход «объём таблицы, ТБ» с учётом: колоночное чтение, отсечение партиций, кэш результатов, период.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«dwh_scan» в families/_w2010_scale_cat_data_eng.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'data_eng.dwh_scan.senior_solve_tb_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
