"""security.cors_waf_rps.junior_solve_rps_k2 — mcq_concept (Junior). Масштабирование узлов межсетевого экрана приложений (WAF) — обратная задача: наибольший допустимый вход «входящий поток запросов/с» с учётом: пиковый коэффициент, глубокий разбор.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«cors_waf_rps» в families/_w2010_scale_cat_security.py, ступень 2 из 5, обратная задача по «rps»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "security.cors_waf_rps.junior_solve_rps_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
