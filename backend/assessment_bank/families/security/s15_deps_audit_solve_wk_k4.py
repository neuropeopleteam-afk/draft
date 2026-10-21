"""security.deps_audit.lead_solve_wk_k4 — mcq_concept (Middle). Время проверки зависимостей и контейнерных образов в CI — обратная задача: наименьший допустимый вход «число параллельных воркеров» с учётом: кэш слоёв, параллельные воркеры, сборка SBOM, повторная проверка.

Модель предметной области (MODEL: answer, traps, fmt), ловушки и тексты — базовая модель
«deps_audit» в families/_w2010_scale_cat_security.py, ступень 4 из 5, обратная задача;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = 'security.deps_audit.lead_solve_wk_k4'
N_ABOVE = (0, 1, 2, 3, 4)  # 5 вариантов ответа: стратифицированное место ключа по величине (0..4 равновероятно)
generate = make(FAMILY_ID, N_ABOVE)
