"""mobile.deeplink_campaign.middle_fwd_k4 — mcq_concept (Middle). Поток открытий экранов по диплинкам из пуш-кампании — прямой расчёт с учётом: недоступные токены, окно переходов, пиковый коэффициент, обновление токена.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«deeplink_campaign» в families/_w2010_scale_cat_mobile.py, ступень 4 из 5, прямой расчёт;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "mobile.deeplink_campaign.middle_fwd_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
