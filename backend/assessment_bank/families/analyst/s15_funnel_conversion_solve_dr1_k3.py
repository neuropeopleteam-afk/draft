"""analyst.funnel_conversion.senior_solve_dr1_k3 — mcq_concept (Senior). Расчёт целевого выхода многошаговой продуктовой воронки — обратная задача: наибольший допустимый вход «доля отвала на анкете, %» с учётом: отвал на анкете, отсев скоринга, не подтвердили СМС.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«funnel_conversion» в families/_w2010_scale_cat_analyst.py, ступень 3 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'analyst.funnel_conversion.senior_solve_dr1_k3'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
