"""qa.defect_escape.senior_solve_ut_k3 — mcq_concept (Senior). Сколько дефектов уходит в прод после этапов контроля — обратная задача: наименьший допустимый вход «доля дефектов, пойманных юнит-тестами, %» с учётом: юнит-тесты, код-ревью, регресс.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«defect_escape» в families/_w2010_scale_cat_qa.py, ступень 3 из 5, обратная задача по «ut»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "qa.defect_escape.senior_solve_ut_k3"
N_ABOVE = (1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
