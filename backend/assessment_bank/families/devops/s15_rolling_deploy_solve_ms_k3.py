"""devops.rolling_deploy.senior_solve_ms_k3 — mcq_concept (Senior). Длительность rolling update деплоя — обратная задача: наименьший допустимый вход «maxSurge, подов» с учётом: время волны, drain, повторы волн.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«rolling_deploy» в families/_w2010_scale_cat_devops.py, ступень 3 из 5, обратная задача по «ms»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "devops.rolling_deploy.senior_solve_ms_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
