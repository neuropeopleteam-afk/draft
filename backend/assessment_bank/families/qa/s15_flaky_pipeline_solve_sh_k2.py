"""qa.flaky_pipeline.middle_solve_sh_k2 — mcq_concept (Middle). Длительность тестового пайплайна с флаки-тестами — обратная задача: наименьший допустимый вход «число шардов» с учётом: шарды, флаки-тесты.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«flaky_pipeline» в families/_w2010_scale_cat_qa.py, ступень 2 из 5, обратная задача по «sh»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "qa.flaky_pipeline.middle_solve_sh_k2"
N_ABOVE = (0, 1)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
