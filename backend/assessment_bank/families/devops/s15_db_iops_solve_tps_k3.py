"""devops.db_iops.middle_solve_tps_k3 — mcq_concept (Middle). IOPS диска под нагрузку базы данных — обратная задача: наибольший допустимый вход «транзакций в секунду» с учётом: кэш буферов, WAL, всплески чекпойнтов.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«db_iops» в families/_w2010_scale_cat_devops.py, ступень 3 из 5, обратная задача по «tps»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "devops.db_iops.middle_solve_tps_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
