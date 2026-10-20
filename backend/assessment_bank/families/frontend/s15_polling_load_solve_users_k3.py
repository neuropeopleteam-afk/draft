"""frontend.polling_load.middle_solve_users_k3 — mcq_concept (Middle). Нагрузка от поллинга вкладок браузера — обратная задача: наибольший допустимый вход «пользователей онлайн» с учётом: вкладки, скрытые вкладки, ретраи.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«polling_load» в families/_w2010_scale_cat_frontend.py, ступень 3 из 5, обратная задача по «users»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "frontend.polling_load.middle_solve_users_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
