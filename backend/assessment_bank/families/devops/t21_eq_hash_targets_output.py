"""devops.net.t21_eq_hash_targets_output — predict_output (набор t21, порог Senior): несогласованные `__eq__` и
`__hash__` у ключей словаря.

Скрипт считает повторы целей балансировщика словарём `{Target: count}`. У `Target` равенство — по имени хоста без
учёта регистра, а хеш — по порту. Правила dict: ключи совпадают, только если равны И хеши, И `__eq__`; при повторе
остаётся ПЕРВЫЙ вставленный ключ (меняется только значение); `in` для списка смотрит лишь на `__eq__`, а для
словаря — сначала на хеш. Хеш int равен самому числу, поэтому результат детерминирован. Ключ — независимая модель
словаря в генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.net.t21_eq_hash_targets_output"

CTX = ["балансировщик API", "пул шлюза платежей", "апстримы поиска", "пул личного кабинета", "апстримы каталога",
       "пул CRM", "апстримы сервиса уведомлений"]
HOSTS = ["api-1", "api-2", "db-1", "web-1", "web-2", "cache-1", "mq-1", "auth-1", "lb-2", "edge-3"]
PORTS = [80, 443, 8080, 9000, 8443]
NAMES = [("Target", "host", "seen", "t", "probe"), ("Upstream", "addr", "counts", "u", "query"),
         ("Backend", "name", "pool", "b", "lookup"), ("Endpoint", "host", "hits", "ep", "needle")]


def _case(h: str, rng) -> str:
    return rng.choice([h, h.upper(), h.capitalize()])


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    cls, at, dv, lv, pv = rng.choice(NAMES)
    for _ in range(500):
        base_hosts = rng.sample(HOSTS, 2)
        ports3 = rng.sample(PORTS, 3)
        k = rng.randint(4, 5)
        seq = []
        for _i in range(k):
            h = rng.choice(base_hosts)
            seq.append((_case(h, rng), rng.choice(ports3)))
        keys: list[list] = []
        for h, p in seq:
            for key in keys:
                if key[1] == p and key[0].lower() == h.lower():
                    key[2] += 1
                    break
            else:
                keys.append([h, p, 1])
        same_host_diff_port = any(a[0].lower() == b[0].lower() and a[1] != b[1] for a in keys for b in keys)
        diff_host_same_port = any(a[0].lower() != b[0].lower() and a[1] == b[1] for a in keys for b in keys)
        # повтор с другим регистром: остаётся первый вставленный объект (его host и печатается)
        dup_case = any(a[1] == b[1] and a[0].lower() == b[0].lower() and a[0] != b[0]
                       for i, a in enumerate(seq) for b in seq[i + 1:])
        if same_host_diff_port and dup_case and diff_host_same_port and len(keys) >= 3:
            break
    else:
        raise RuntimeError("t21_eq_hash_targets: не подобран набор")
    ph = _case(rng.choice(base_hosts), rng)
    if rng.random() < 0.6:  # чаще — хост есть, но с другим портом: списку «равен», словарю — нет
        taken = {key[1] for key in keys if key[0].lower() == ph.lower()}
        pp = rng.choice([p for p in PORTS if p not in taken])
    else:
        pp = rng.choice(PORTS)
    in_list = any(key[0].lower() == ph.lower() for key in keys)
    in_dict = any(key[0].lower() == ph.lower() and key[1] == pp for key in keys)
    targets = ", ".join(f'{cls}("{h}", {p})' for h, p in seq)
    lines = [f"class {cls}:",
             f"    def __init__(self, {at}, port):",
             f"        self.{at}, self.port = {at}, port",
             "    def __eq__(self, other):",
             f"        return self.{at}.lower() == other.{at}.lower()",
             "    def __hash__(self):",
             "        return self.port",
             "",
             f"{dv} = {{}}",
             f"for {lv} in [{targets}]:",
             f"    {dv}[{lv}] = {dv}.get({lv}, 0) + 1",
             f"for {lv}, n in {dv}.items():",
             f"    print({lv}.{at}, {lv}.port, n)",
             f'{pv} = {cls}("{ph}", {pp})',
             f"print({pv} in list({dv}), {pv} in {dv})"]
    code = "\n".join(lines)
    outs = [f"{h} {p} {c}" for h, p, c in keys] + [f"{in_list} {in_dict}"]
    out = "\n".join(outs)
    expl = ("Ключ словаря совпадает с существующим, только если равны хеши (порты) И __eq__ (хост без учёта регистра). "
            "Одинаковый хост с другим портом — другой хеш, отдельный ключ; другой хост с тем же портом — __eq__ ложно, "
            "тоже отдельный ключ; при повторе остаётся первый вставленный объект, растёт только счётчик. Итог: "
            + "; ".join(f"{h}:{p} — {c}" for h, p, c in keys)
            + f". `{pv} in list({dv})` проверяет только __eq__ → {in_list}; `{pv} in {dv}` сначала ищет хеш "
            f"{pp} → {in_dict}. Вывод по строкам: " + " / ".join(f"«{x}»" for x in outs) + ".")
    stem = f"Скрипт собирает цели ({ctx}) и считает повторы словарём с объектами {cls} в качестве ключей."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"seq": seq, "probe": [ph, pp]}, language="python")
