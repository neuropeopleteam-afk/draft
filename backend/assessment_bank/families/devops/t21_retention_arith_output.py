"""devops.disk.t21_retention_arith_output — predict_output (набор t21, порог Стажёра): приоритет операций и
целочисленное деление в `$(( ))` bash.

Скрипт оценивает место под логи: запас + суточный объём × число дней хранения, затем долю диска в процентах.
Ловушки чтения: умножение в `base + per_day * days` выполняется раньше сложения; `$(( need * 100 / disk ))`
делит нацело (дробная часть отбрасывается, не округляется). Ключ — независимый расчёт в генераторе; проверка —
исполнение показанного скрипта в bash-песочнице.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.disk.t21_retention_arith_output"

CTX = [("логи биллинга", "billing"), ("логи каталога", "catalog"), ("журналы платёжного шлюза", "payments"),
       ("логи поиска", "search"), ("журналы личного кабинета", "lk"), ("логи сервиса уведомлений", "notify"),
       ("журналы CRM", "crm")]
NAMES = [("per_day", "days", "base", "need", "disk"), ("daily", "keep", "reserve", "need", "size"),
         ("gb_day", "ttl", "spare", "total", "volume"), ("day_gb", "retention", "extra", "want", "disk_gb")]
DISKS = [100, 150, 200, 250, 300, 400, 500]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, svc = rng.choice(CTX)
    p, d, b, n, v = rng.choice(NAMES)
    for _ in range(500):
        per_day = rng.randint(3, 19)
        days = rng.randint(4, 14)
        base = rng.randint(5, 40)
        disk = rng.choice(DISKS)
        need = base + per_day * days
        wrong = (base + per_day) * days
        if need >= disk or (need * 100) % disk == 0 or wrong == need:
            continue
        break
    else:
        raise RuntimeError("t21_retention_arith: не подобраны числа")
    pct = need * 100 // disk
    code = (f"{p}={per_day}\n"
            f"{d}={days}\n"
            f"{b}={base}\n"
            f"{n}=$(( {b} + {p} * {d} ))\n"
            f"{v}={disk}\n"
            f'echo "{svc}: ${{{n}}}G"\n'
            f'echo "used: $(( {n} * 100 / {v} ))%"')
    out = f"{svc}: {need}G\nused: {pct}%"
    exact = f"{need * 100 / disk:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    expl = (f"{n} = {base} + {per_day} × {days} = {need}: умножение выполняется раньше сложения "
            f"(({base} + {per_day}) × {days} = {wrong} — ошибка чтения). Доля: {need} × 100 / {disk} = {exact}, "
            f"но $(( )) делит нацело и отбрасывает дробную часть — {pct}. Вывод: «{svc}: {need}G» и «used: {pct}%».")
    stem = (f"Скрипт оценивает, сколько места на диске займут {ctx} при заданном сроке хранения, и печатает "
            f"объём и долю диска.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"per_day": per_day, "days": days, "base": base, "disk": disk}, language="bash")
