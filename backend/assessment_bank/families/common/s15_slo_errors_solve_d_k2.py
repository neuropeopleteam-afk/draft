"""common.slo_errors.junior_solve_d_k2 — mcq_concept (Junior). Остаток бюджета ошибок SLO в запросах — обратная задача: наименьший допустимый вход «длина окна SLO в днях» с учётом: израсходованная часть бюджета, трафик ботов вне SLI.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«slo_errors» в families/_w2010_scale_cat_common.py, ступень 2 из 5, обратная задача по «D»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "common.slo_errors.junior_solve_d_k2"
N_ABOVE = (0, 1, 2)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
