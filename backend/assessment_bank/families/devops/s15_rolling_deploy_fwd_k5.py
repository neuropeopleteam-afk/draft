"""devops.rolling_deploy.senior_fwd_k5 — mcq_concept (Senior). Длительность rolling update деплоя — прямой расчёт с учётом: время волны, drain, повторы волн, кластеры, smoke-тесты.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«rolling_deploy» в families/_w2010_scale_cat_devops.py, ступень 5 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'devops.rolling_deploy.senior_fwd_k5'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
