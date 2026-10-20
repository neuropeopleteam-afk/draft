"""qa.manual_regress.lead_solve_n_k5 — mcq_concept (Principal). Длительность ручного регресса перед релизом — обратная задача: наибольший допустимый вход «тест-кейсов» с учётом: автоматизация, тестировщики, платформы, перепроверки, подготовка.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«manual_regress» в families/_w2010_scale_cat_qa.py, ступень 5 из 5, обратная задача по «n»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "qa.manual_regress.lead_solve_n_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
