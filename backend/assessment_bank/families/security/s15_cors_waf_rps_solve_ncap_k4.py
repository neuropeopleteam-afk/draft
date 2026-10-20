"""security.cors_waf_rps.lead_solve_ncap_k4 — mcq_concept (Lead). Масштабирование узлов межсетевого экрана приложений (WAF) — обратная задача: наименьший допустимый вход «производительность одного узла, запросов/с» с учётом: пиковый коэффициент, глубокий разбор, разгрузка CDN, запас по загрузке.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«cors_waf_rps» в families/_w2010_scale_cat_security.py, ступень 4 из 5, обратная задача по «ncap»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "security.cors_waf_rps.lead_solve_ncap_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
