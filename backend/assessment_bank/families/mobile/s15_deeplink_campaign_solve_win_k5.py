"""mobile.deeplink_campaign.principal_solve_win_k5 — mcq_concept (Principal). Поток открытий экранов по диплинкам из пуш-кампании — обратная задача: наименьший допустимый вход «длительность окна размытия рассылки, с» с учётом: недоступные токены, окно переходов, пиковый коэффициент, обновление токена, запросы атрибуции.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«deeplink_campaign» в families/_w2010_scale_cat_mobile.py, ступень 5 из 5, обратная задача по «win»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "mobile.deeplink_campaign.principal_solve_win_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
