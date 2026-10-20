"""qa.api_test_suite.lead_solve_ep_k5 — mcq_concept (Principal). Размер набора тестов API за цикл — обратная задача: наибольший допустимый вход «число эндпоинтов» с учётом: негативные сценарии, окружения, контрактные тесты, две версии API, тесты безопасности.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«api_test_suite» в families/_w2010_scale_cat_qa.py, ступень 5 из 5, обратная задача по «ep»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "qa.api_test_suite.lead_solve_ep_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
