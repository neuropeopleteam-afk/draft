"""security.siem_storage.lead_solve_eps_k5 — mcq_concept (Senior). Объём хранилища журнала событий ИБ (SIEM) — обратная задача: наибольший допустимый вход «поток событий, событий/с» с учётом: пиковый коэффициент, фильтрация шума, индексы поиска, репликация, запас по загрузке.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«siem_storage» в families/_w2010_scale_cat_security.py, ступень 5 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'security.siem_storage.lead_solve_eps_k5'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
