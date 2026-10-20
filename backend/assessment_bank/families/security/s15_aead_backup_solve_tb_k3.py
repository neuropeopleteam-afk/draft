"""security.aead_backup.middle_solve_tb_k3 — mcq_concept (Middle). Длительность шифрования и выгрузки резервной копии — обратная задача: наибольший допустимый вход «объём базы, ТБ» с учётом: сжатие, потоки шифрования, проверка тегов.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«aead_backup» в families/_w2010_scale_cat_security.py, ступень 3 из 5, обратная задача по «tb»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "security.aead_backup.middle_solve_tb_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
