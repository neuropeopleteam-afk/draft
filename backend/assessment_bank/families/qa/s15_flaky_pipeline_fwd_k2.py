"""qa.flaky_pipeline.intern_fwd_k2 — mcq_concept (Стажёр). Длительность тестового пайплайна с флаки-тестами — прямой расчёт с учётом: шарды, флаки-тесты.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«flaky_pipeline» в families/_w2010_scale_cat_qa.py, ступень 2 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'qa.flaky_pipeline.intern_fwd_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
