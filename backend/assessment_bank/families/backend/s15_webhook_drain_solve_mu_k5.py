"""backend.webhook_drain.principal_solve_mu_k5 — mcq_concept (Senior). Время разбора очереди вебхуков после сбоя — обратная задача: наименьший допустимый вход «скорость одного воркера, событий в секунду» с учётом: параллельные воркеры, входящий поток, повторы доставки, подпись и логирование, простой на перезапуск.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«webhook_drain» в families/_w2010_scale_cat_backend.py, ступень 5 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'backend.webhook_drain.principal_solve_mu_k5'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
