"""security.hmac_webhook.middle_solve_us_k2 — mcq_concept (Middle). Пропускная способность контура проверки подписей вебхуков — обратная задача: наибольший допустимый вход «затраты CPU на сообщение, мкс» с учётом: пиковый коэффициент, повторные доставки.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«hmac_webhook» в families/_w2010_scale_cat_security.py, ступень 2 из 5, обратная задача по «us»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "security.hmac_webhook.middle_solve_us_k2"
N_ABOVE = (1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
