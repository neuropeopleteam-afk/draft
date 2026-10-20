"""security.tls_gateway.principal_solve_cops_k5 — mcq_concept (Principal). Число ядер шлюза терминации TLS — обратная задача: наименьший допустимый вход «рукопожатий/с на ядро» с учётом: возобновление сессий, пиковый коэффициент, проверка mTLS, запас по загрузке, фоновые задачи.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«tls_gateway» в families/_w2010_scale_cat_security.py, ступень 5 из 5, обратная задача по «cops»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "security.tls_gateway.principal_solve_cops_k5"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
