"""analyst.support_escalation_cap.senior_solve_dau_k4 — mcq_concept (Senior). Расчёт пропускной способности линии разбора инцидентов и обращений — обратная задача: наибольший допустимый вход «суточная аудитория сервиса, тыс.» с учётом: самообслуживание бота, решение на L1, повторные касания, выработка инженера L2.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«support_escalation_cap» в families/_w2010_scale_cat_analyst.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'analyst.support_escalation_cap.senior_solve_dau_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
