"""security.hmac_webhook.senior_solve_wh_k4 — mcq_concept (Lead). Пропускная способность контура проверки подписей вебхуков — обратная задача: наибольший допустимый вход «базовый поток вебхуков/с» с учётом: пиковый коэффициент, повторные доставки, проверка nonce, запас по загрузке.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«hmac_webhook» в families/_w2010_scale_cat_security.py, ступень 4 из 5, обратная задача по «wh»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "security.hmac_webhook.senior_solve_wh_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
