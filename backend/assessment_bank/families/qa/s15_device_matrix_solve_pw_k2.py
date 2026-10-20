"""qa.device_matrix.middle_solve_pw_k2 — mcq_concept (Middle). Число прогонов в матрице устройств — обратная задача: наибольший допустимый вход «доля комбинаций после pairwise, %» с учётом: локали, pairwise-сокращение.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«device_matrix» в families/_w2010_scale_cat_qa.py, ступень 2 из 5, обратная задача по «pw»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "qa.device_matrix.middle_solve_pw_k2"
N_ABOVE = (1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
