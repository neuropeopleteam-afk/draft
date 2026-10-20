"""analyst.support_escalation_cap.middle_solve_bot_k2 — mcq_concept (Middle). Расчёт пропускной способности линии разбора инцидентов и обращений — обратная задача: наименьший допустимый вход «доля автоматического закрытия ботом, %» с учётом: самообслуживание бота, решение на L1.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«support_escalation_cap» в families/_w2010_scale_cat_analyst.py, ступень 2 из 5, обратная задача по «bot»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "analyst.support_escalation_cap.middle_solve_bot_k2"
N_ABOVE = (3,)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
