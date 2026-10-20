"""qa.manual_regress.lead_solve_au_k4 — mcq_concept (Lead). Длительность ручного регресса перед релизом — обратная задача: наименьший допустимый вход «доля автоматизации, %» с учётом: автоматизация, тестировщики, платформы, перепроверки.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«manual_regress» в families/_w2010_scale_cat_qa.py, ступень 4 из 5, обратная задача по «au»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "qa.manual_regress.lead_solve_au_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
