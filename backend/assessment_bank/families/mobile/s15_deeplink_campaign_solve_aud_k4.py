"""mobile.deeplink_campaign.senior_solve_aud_k4 — mcq_concept (Senior). Поток открытий экранов по диплинкам из пуш-кампании — обратная задача: наибольший допустимый вход «размер базы пуш-рассылки, тыс.» с учётом: недоступные токены, окно переходов, пиковый коэффициент, обновление токена.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«deeplink_campaign» в families/_w2010_scale_cat_mobile.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'mobile.deeplink_campaign.senior_solve_aud_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
