"""security.deps_audit.middle_solve_srv_k3 — mcq_concept (Middle). Время проверки зависимостей и контейнерных образов в CI — обратная задача: наибольший допустимый вход «число сервисов в релизе» с учётом: кэш слоёв, параллельные воркеры, сборка SBOM.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«deps_audit» в families/_w2010_scale_cat_security.py, ступень 3 из 5, обратная задача по «srv»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "security.deps_audit.middle_solve_srv_k3"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
