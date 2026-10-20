"""analyst.funnel_conversion.middle_solve_dr1_k2 — mcq_concept (Middle). Расчёт целевого выхода многошаговой продуктовой воронки — обратная задача: наибольший допустимый вход «доля отвала на анкете, %» с учётом: отвал на анкете, отсев скоринга.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«funnel_conversion» в families/_w2010_scale_cat_analyst.py, ступень 2 из 5, обратная задача по «dr1»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "analyst.funnel_conversion.middle_solve_dr1_k2"
N_ABOVE = (2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
