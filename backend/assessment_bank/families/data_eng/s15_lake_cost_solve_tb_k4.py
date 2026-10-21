"""data_eng.lake_cost.senior_solve_tb_k4 — mcq_concept (Senior). Месячная стоимость хранения озера данных в S3 — обратная задача: наибольший допустимый вход «сырые данные, ТБ» с учётом: сжатие, холодный класс, версионирование, запросы.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«lake_cost» в families/_w2010_scale_cat_data_eng.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'data_eng.lake_cost.senior_solve_tb_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
