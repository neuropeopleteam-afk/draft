"""devops.db_iops.senior_solve_tps_k4 — mcq_concept (Lead). IOPS диска под нагрузку базы данных — обратная задача: наибольший допустимый вход «транзакций в секунду» с учётом: кэш буферов, WAL, всплески чекпойнтов, запас по IOPS.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«db_iops» в families/_w2010_scale_cat_devops.py, ступень 4 из 5, обратная задача по «tps»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "devops.db_iops.senior_solve_tps_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
