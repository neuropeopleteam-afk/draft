"""qa.api_test_suite.senior_solve_cs_k3 — mcq_concept (Senior). Размер набора тестов API за цикл — обратная задача: наибольший допустимый вход «позитивных сценариев на эндпоинт» с учётом: негативные сценарии, окружения, контрактные тесты.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«api_test_suite» в families/_w2010_scale_cat_qa.py, ступень 3 из 5, обратная задача по «cs»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "qa.api_test_suite.senior_solve_cs_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
