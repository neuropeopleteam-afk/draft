"""common.cloud_cost.lead_solve_p_k4 — mcq_concept (Middle). Месячный счёт за облачные виртуальные машины — обратная задача: наибольший допустимый вход «тариф за час, ₽» с учётом: скидка, диски и трафик, рост парка, деление между командами.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«cloud_cost» в families/_w2010_scale_cat_common.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'common.cloud_cost.lead_solve_p_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
