"""qa.api_test_suite.junior_solve_ep_k2 — mcq_concept (Junior). Размер набора тестов API за цикл — обратная задача: наибольший допустимый вход «число эндпоинтов» с учётом: негативные сценарии, окружения.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«api_test_suite» в families/_w2010_scale_cat_qa.py, ступень 2 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'qa.api_test_suite.junior_solve_ep_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
