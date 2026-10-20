"""mobile.bundle_ota_size.senior_solve_r8_k3 — mcq_concept (Senior). Размер установочного пакета и ресурсов мобильного релиза — обратная задача: наименьший допустимый вход «степень сжатия R8/Stripping, %» с учётом: оптимизация R8/Stripping, сплит App Bundle, локальные ML-модели.

Модель предметной области (MODEL: answer, traps, fmt, brute), ловушки и тексты — базовая модель
«bundle_ota_size» в families/_w2010_scale_cat_mobile.py, ступень 3 из 5, обратная задача по «r8»;
текст модели семейства собирает _w2010_scale_defs.model_source, генерация — _w2010_kit.numeric_variant.
"""
from assessment_bank.families._w2010_scale_defs import make

FAMILY_ID = "mobile.bundle_ota_size.senior_solve_r8_k3"
N_ABOVE = (2, 3)  # при каком числе ловушек «выше ключа» подбор выполним (пробная выборка генератора волны)
generate = make(FAMILY_ID, N_ABOVE)
