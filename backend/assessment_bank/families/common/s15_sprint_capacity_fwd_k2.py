"""common.sprint_capacity.intern_fwd_k2 — mcq_concept (Стажёр). Ёмкость спринта команды в стори-пойнтах — прямой расчёт с учётом: отпуска и дежурства, встречи и ревью.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«sprint_capacity» в families/_w2010_scale_cat_common.py, ступень 2 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'common.sprint_capacity.intern_fwd_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
