"""data_eng.dwh_scan.lead_solve_tb_k5 — mcq_concept (Principal). Стоимость сканирования данных в облачном DWH — обратная задача: наибольший допустимый вход «объём таблицы, ТБ» с учётом: колоночное чтение, отсечение партиций, кэш результатов, период, хранение.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«dwh_scan» в families/_w2010_scale_cat_data_eng.py, ступень 5 из 5, обратная задача по «tb»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "data_eng.dwh_scan.lead_solve_tb_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
