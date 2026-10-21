"""security.siem_storage.junior_solve_eps_k2 — mcq_concept (Junior). Объём хранилища журнала событий ИБ (SIEM) — обратная задача: наибольший допустимый вход «поток событий, событий/с» с учётом: пиковый коэффициент, фильтрация шума.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«siem_storage» в families/_w2010_scale_cat_security.py, ступень 2 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'security.siem_storage.junior_solve_eps_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
