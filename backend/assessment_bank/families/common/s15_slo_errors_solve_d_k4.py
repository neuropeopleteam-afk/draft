"""common.slo_errors.senior_solve_d_k4 — mcq_concept (Senior). Остаток бюджета ошибок SLO в запросах — обратная задача: наименьший допустимый вход «длина окна SLO в днях» с учётом: израсходованная часть бюджета, трафик ботов вне SLI, резерв под релизы, деление по регионам.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«slo_errors» в families/_w2010_scale_cat_common.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'common.slo_errors.senior_solve_d_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
