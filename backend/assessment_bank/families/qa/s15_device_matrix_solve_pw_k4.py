"""qa.device_matrix.lead_solve_pw_k4 — mcq_concept (Middle). Число прогонов в матрице устройств — обратная задача: наибольший допустимый вход «доля комбинаций после pairwise, %» с учётом: локали, pairwise-сокращение, тесты на комбинацию, перезапуски.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«device_matrix» в families/_w2010_scale_cat_qa.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'qa.device_matrix.lead_solve_pw_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
