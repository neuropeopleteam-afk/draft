"""devops.mon.t21_and_or_alert_output — predict_output (набор t21, порог Стажёра): приоритет `and` над `or`
в условии алерта (Python).

Проверка нагрузки по хостам: `if cpu > X or mem > Y and disk > Z` — `and` связывает сильнее, поэтому условие читается
как `cpu > X or (mem > Y and disk > Z)`, а не «слева направо» `(cpu > X or mem > Y) and disk > Z`. В каждом
варианте есть хост, на котором два прочтения расходятся (высокий CPU при малой загрузке диска), и хост, который
срабатывает только по ветке `and`. Ключ — независимая модель в генераторе; проверка — исполнение показанного кода
в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.mon.t21_and_or_alert_output"

CTX = [("кластер биллинга", "bill"), ("узлы каталога", "cat"), ("серверы платёжного шлюза", "pay"),
       ("кластер поиска", "search"), ("серверы личного кабинета", "lk"), ("узлы очереди", "mq"),
       ("серверы CRM", "crm")]
ROLES = ["web", "api", "db", "cache", "worker", "proxy"]
METRICS = [("cpu", "mem", "disk"), ("cpu", "ram", "disk"), ("load", "mem", "disk"), ("cpu", "mem", "inodes")]
LABELS = [("ALERT", "ok"), ("PAGE", "ok"), ("ALERT", "fine"), ("CRIT", "ok")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, px = rng.choice(CTX)
    ma, mb, mc = rng.choice(METRICS)
    ta, tb, tc = rng.choice([80, 85, 90]), rng.choice([85, 90, 95]), rng.choice([80, 85, 90])
    hi, lo = rng.choice(LABELS)
    n = 3
    # типы хостов: diff — A истинно, C ложно (прочтения расходятся); and — только ветка B and C; ok — ничего;
    # b_only — B истинно, C ложно (ловушка «or по B»)
    kinds = ["diff", "and", rng.choice(["ok", "b_only"])]
    rng.shuffle(kinds)
    names = rng.sample([f"{px}-{r}{i}" for r in ROLES for i in (1, 2)], n)

    def val(true: bool, t: int) -> int:
        return rng.randint(t + 1, 99) if true else rng.randint(20, t - 1)

    hosts, out_lines, notes = [], [], []
    for name, kind in zip(names, kinds):
        a = kind == "diff"
        b = kind in ("and", "b_only") or (kind == "diff" and rng.random() < 0.5)
        c = kind == "and"
        va, vb, vc = val(a, ta), val(b, tb), val(c, tc)
        hosts.append((name, va, vb, vc))
        fired = a or (b and c)
        out_lines.append(f"{name} {hi if fired else lo}")
        notes.append(f"{name}: {va > ta} or ({vb > tb} and {vc > tc}) → {'True' if fired else 'False'}")
    rows = ", ".join(f'("{h[0]}", {h[1]}, {h[2]}, {h[3]})' for h in hosts)
    code = (f"hosts = [{rows}]\n"
            f"for name, {ma}, {mb}, {mc} in hosts:\n"
            f"    if {ma} > {ta} or {mb} > {tb} and {mc} > {tc}:\n"
            f'        print(name, "{hi}")\n'
            "    else:\n"
            f'        print(name, "{lo}")')
    out = "\n".join(out_lines)
    expl = (f"`and` связывает сильнее `or`: условие — {ma} > {ta} or ({mb} > {tb} and {mc} > {tc}). "
            + "; ".join(notes) + f". Прочтение слева направо (({ma} > {ta} or {mb} > {tb}) and {mc} > {tc}) "
            "даёт другой ответ для хоста с высоким " + ma + " и малым " + mc + f". Вывод: {' / '.join(out_lines)}.")
    stem = f"Скрипт мониторинга ({ctx}) проверяет метрики хостов и решает, поднимать ли тревогу."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"kinds": kinds, "thresholds": [ta, tb, tc]}, language="python")
