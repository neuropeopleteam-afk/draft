"""common.slo_errors.lead_solve_d_k5 — mcq_concept (Principal). Остаток бюджета ошибок SLO в запросах — обратная задача: наименьший допустимый вход «длина окна SLO в днях» с учётом: израсходованная часть бюджета, трафик ботов вне SLI, резерв под релизы, деление по регионам, ошибки текущего инцидента.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«slo_errors» в families/_w2010_scale_cat_common.py, ступень 5 из 5, обратная задача по «D»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "common.slo_errors.lead_solve_d_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
