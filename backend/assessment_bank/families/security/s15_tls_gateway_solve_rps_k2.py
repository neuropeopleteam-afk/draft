"""security.tls_gateway.junior_solve_rps_k2 — mcq_concept (Junior). Число ядер шлюза терминации TLS — обратная задача: наибольший допустимый вход «входящий поток соединений/с» с учётом: возобновление сессий, пиковый коэффициент.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«tls_gateway» в families/_w2010_scale_cat_security.py, ступень 2 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'security.tls_gateway.junior_solve_rps_k2'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
