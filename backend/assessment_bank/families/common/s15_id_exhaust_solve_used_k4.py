"""common.id_exhaust.lead_solve_used_k4 — mcq_concept (Middle). Сколько дней осталось до исчерпания INTEGER-идентификаторов — обратная задача: наибольший допустимый вход «занятая доля диапазона, %» с учётом: рост потока, резерв диапазона, пакетная загрузка, шардирование последовательностей.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«id_exhaust» в families/_w2010_scale_cat_common.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'common.id_exhaust.lead_solve_used_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
