"""common.id_exhaust.lead_solve_lam_k5 — mcq_concept (Principal). Сколько дней осталось до исчерпания INTEGER-идентификаторов — обратная задача: наибольший допустимый вход «поток вставок в секунду» с учётом: рост потока, резерв диапазона, пакетная загрузка, шардирование последовательностей, длительность миграции.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«id_exhaust» в families/_w2010_scale_cat_common.py, ступень 5 из 5, обратная задача по «lam»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "common.id_exhaust.lead_solve_lam_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
