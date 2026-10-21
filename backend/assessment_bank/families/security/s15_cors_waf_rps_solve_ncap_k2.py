"""security.cors_waf_rps.middle_solve_ncap_k2 — mcq_concept (Middle). Масштабирование узлов межсетевого экрана приложений (WAF) — обратная задача: наименьший допустимый вход «производительность одного узла, запросов/с» с учётом: пиковый коэффициент, глубокий разбор.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«cors_waf_rps» в families/_w2010_scale_cat_security.py, ступень 2 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'security.cors_waf_rps.middle_solve_ncap_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
