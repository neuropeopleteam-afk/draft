"""Bash-мониторинг учебного журнала без идентификации людей и команд воздействия."""
from __future__ import annotations

from collections import Counter
from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check
from ._support import CONTEXTS

FAMILY_ID = "security.monitor.log_monitor_output"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CONTEXTS)
    cutoff = rng.randint(100, 800)
    threshold = rng.choice([2, 3, 4])
    # Калибровка 05.10: 17 строк журнала давали канцелярскую нагрузку без новых ловушек;
    # сессий 2 вместо 3 (все четыре ловушки — граница, статус, событие, порог — сохранены)
    subjects = [f"demo-session-{i}" for i in rng.sample(range(10, 99), 2)]
    rows = []
    for i, subject in enumerate(subjects):
        for _ in range(threshold + (1 if i == 0 else -1)):
            rows.append((cutoff + rng.randint(0, 50), subject, "auth_fail", 401))
        rows += [(cutoff - 1, subject, "auth_fail", 401),
                 (cutoff + 1, subject, "auth_ok", 200),
                 (cutoff + 2, subject, "object_denied", 403),
                 (cutoff + 3, subject, "auth_fail", 500)]
    rng.shuffle(rows)
    log = "\n".join(" ".join(map(str, r)) for r in rows) + "\n"
    cmd = (f"awk '$1 >= {cutoff} && $3 == \"auth_fail\" && $4 == 401 {{n[$2]++}} "
           f"END {{for (s in n) if (n[s] >= {threshold}) print s, n[s]}}' events.log | sort")
    counts = Counter(s for ts, s, event, status in rows
                     if ts >= cutoff and event == "auth_fail" and status == 401)
    out = "\n".join(f"{s} {counts[s]}" for s in sorted(counts) if counts[s] >= threshold)
    stem = (f"{ctx.capitalize()}: мониторинг отмечает группы с не менее чем {threshold} "
            f"событиями auth_fail/401 начиная с секунды {cutoff}, граница включена. "
            "Формат журнала: `секунда учебная_сессия событие статус`. Это лишь сигнал для "
            "проверки, не доказательство нарушения и не команда блокировки. Что выведет "
            f"конвейер? Результат сортируется лексикографически.\n\n{log}")
    return build_variant(
        FAMILY_ID, seed, stem=stem, code=cmd, context=ctx, verification="execution",
        answer_key=AnswerKey(kind="output", value=out, explanation="Считаются только auth_fail "
                            "с кодом 401 в заданном окне. Успехи, object_denied, 500 и старые "
                            "события исключаются. Порог проверяется после группировки."),
        checks=[Check(name="stdout", runner="bash", program=cmd, files={"events.log": log},
                      expect="stdout_equals", expected_stdout=out)],
        params={"threshold": threshold, "cutoff": cutoff, "rows": rows},
    )
