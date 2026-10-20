"""security.rbac_cache.lead_solve_usr_k5 — mcq_concept (Principal). Объём оперативной памяти под кэш матриц прав доступа (RBAC) — обратная задача: наибольший допустимый вход «активных пользователей, тыс.» с учётом: пиковый коэффициент, накладные расходы структуры, журнал отзывов, реплики кэша, запас по загрузке.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«rbac_cache» в families/_w2010_scale_cat_security.py, ступень 5 из 5, обратная задача по «usr»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "security.rbac_cache.lead_solve_usr_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
