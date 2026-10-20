"""security.siem_storage.middle_solve_d_k2 — mcq_concept (Middle). Объём хранилища журнала событий ИБ (SIEM) — обратная задача: наибольший допустимый вход «срок хранения, дней» с учётом: пиковый коэффициент, фильтрация шума.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«siem_storage» в families/_w2010_scale_cat_security.py, ступень 2 из 5, обратная задача по «d»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "security.siem_storage.middle_solve_d_k2"
N_ABOVE = (0, 1, 2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
