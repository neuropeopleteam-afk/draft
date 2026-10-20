"""security.rbac_cache.lead_solve_pr_k4 — mcq_concept (Lead). Объём оперативной памяти под кэш матриц прав доступа (RBAC) — обратная задача: наибольший допустимый вход «правил на пользователя» с учётом: пиковый коэффициент, накладные расходы структуры, журнал отзывов, реплики кэша.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«rbac_cache» в families/_w2010_scale_cat_security.py, ступень 4 из 5, обратная задача по «pr»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "security.rbac_cache.lead_solve_pr_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
