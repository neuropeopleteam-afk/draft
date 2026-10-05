"""`make validate` — заготовка процедуры валидации.

Будущие метрики (см. docs/ARCHITECTURE.md): precision@k подбора на размеченных парах «потребность — кандидат»,
стабильность грейда при повторном прохождении, дискриминативность заданий, устойчивость к утечке банка.
"""
import json
import sys

from app.core.db import utcnow

CHECKS = [
    ("matching.precision_at_k", "Доля релевантных кандидатов в топ-k подборки"),
    ("assessment.test_retest", "Согласованность грейда при повторном прохождении"),
    ("assessment.discrimination", "Дискриминативность заданий (сильные vs слабые)"),
    ("assessment.leak_resistance", "Устойчивость к раскрытию части банка"),
    ("bank.determinism", "Детерминизм генераторов по seed и соблюдение инвариантов"),
]


def main() -> int:
    report = {
        "generated_at": utcnow().isoformat(),
        "status": "stub",
        "checks": [{"id": cid, "title": title, "status": "not_implemented"} for cid, title in CHECKS],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
