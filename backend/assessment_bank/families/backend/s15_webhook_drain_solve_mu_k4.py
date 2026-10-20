"""backend.webhook_drain.lead_solve_mu_k4 — mcq_concept (Lead). Время разбора очереди вебхуков после сбоя — обратная задача: наименьший допустимый вход «скорость одного воркера, событий в секунду» с учётом: параллельные воркеры, входящий поток, повторы доставки, подпись и логирование.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«webhook_drain» в families/_w2010_scale_cat_backend.py, ступень 4 из 5, обратная задача по «mu»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "backend.webhook_drain.lead_solve_mu_k4"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
