"""qa.load_vusers.intern_fwd_k2 — mcq_concept (Стажёр). Число виртуальных пользователей в нагрузочном тесте — прямой расчёт с учётом: пиковый коэффициент, запас на ошибки.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«load_vusers» в families/_w2010_scale_cat_qa.py, ступень 2 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'qa.load_vusers.intern_fwd_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
