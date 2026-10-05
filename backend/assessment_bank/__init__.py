"""assessment_bank — банк заданий спецтрека ФСП (ЛЦТ 2026).

Чистый Python без БД. Основные точки входа:

    from assessment_bank import generate, list_families, get_spec
    v = generate("common.alg.binary_search_bound", seed=17)
    v.public_view()   # можно отдавать кандидату (без ключа и рубрики)

Подпакеты: ``psychometrics`` (Раш/2PL, иерархия семейств, адаптивный тест, грейды,
детектор предзнания), ``simulation`` (синтетическая проверка), ``validator``.
"""
from .registry import canary_published_seeds, generate, get_spec, list_families, load_specs
from .schema import FamilySpec, Variant

__all__ = ["generate", "get_spec", "list_families", "load_specs", "canary_published_seeds",
           "FamilySpec", "Variant"]
__version__ = "0.1.0"
