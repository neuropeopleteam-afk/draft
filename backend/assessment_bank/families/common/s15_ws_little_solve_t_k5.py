"""common.ws_little.principal_solve_t_k5 — mcq_concept (Principal). Одновременные соединения по закону Литтла на узел балансировщика — обратная задача: наибольший допустимый вход «длительность сессии в минутах» с учётом: пиковый коэффициент, соединения на сессию, деление по узлам, запас по загрузке, резерв соединений.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«ws_little» в families/_w2010_scale_cat_common.py, ступень 5 из 5, обратная задача по «t»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "common.ws_little.principal_solve_t_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
