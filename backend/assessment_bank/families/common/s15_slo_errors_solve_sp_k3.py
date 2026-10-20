"""common.slo_errors.senior_solve_sp_k3 — mcq_concept (Senior). Остаток бюджета ошибок SLO в запросах — обратная задача: наибольший допустимый вход «израсходованная доля бюджета, %» с учётом: израсходованная часть бюджета, трафик ботов вне SLI, резерв под релизы.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«slo_errors» в families/_w2010_scale_cat_common.py, ступень 3 из 5, обратная задача по «sp»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "common.slo_errors.senior_solve_sp_k3"
N_ABOVE = (3,)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
