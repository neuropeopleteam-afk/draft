"""qa.coverage_effort.lead_solve_loc_k5 — mcq_concept (Principal). Трудозатраты на рост покрытия тестами — обратная задача: наибольший допустимый вход «размер кода, тыс. строк» с учётом: строки на тест, темп написания, рост кода, ревью, настройка отчётов.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«coverage_effort» в families/_w2010_scale_cat_qa.py, ступень 5 из 5, обратная задача по «loc»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "qa.coverage_effort.lead_solve_loc_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
