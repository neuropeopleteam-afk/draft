"""qa.flaky_pipeline.senior_solve_sh_k3 — mcq_concept (Senior). Длительность тестового пайплайна с флаки-тестами — обратная задача: наименьший допустимый вход «число шардов» с учётом: шарды, флаки-тесты, поднятие окружения.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«flaky_pipeline» в families/_w2010_scale_cat_qa.py, ступень 3 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'qa.flaky_pipeline.senior_solve_sh_k3'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
