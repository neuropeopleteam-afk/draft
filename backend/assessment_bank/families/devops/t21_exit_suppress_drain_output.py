"""devops.ops.t21_exit_suppress_drain_output — predict_output (набор t21, порог Senior): контекстный менеджер,
чей `__exit__` подавляет часть исключений.

Скрипт обслуживания по очереди выводит узлы из балансировки (`with Drain(host)`), патчит и возвращает. `__exit__`
печатает тип исключения и возвращает истину для «сетевых» ошибок — такие исключения подавляются, и выполнение идёт
дальше ПОСЛЕ блока with; остальные уходят во внешний except. Правило подавления в вариантах разное: `is
TimeoutError`, `issubclass(..., OSError)` (TimeoutError, ConnectionError, PermissionError, FileNotFoundError —
подклассы OSError), `isinstance(exc, (...))`. Ключ — независимая модель в генераторе; проверка — исполнение
показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.ops.t21_exit_suppress_drain_output"

CTX = [("патч узлов базы биллинга", "db"), ("обновление ядра на узлах каталога", "node"),
       ("ротация сертификатов шлюза", "gw"), ("перезапуск узлов поиска", "search"),
       ("обновление агентов личного кабинета", "lk"), ("патч узлов очереди", "mq"), ("обслуживание узлов CRM", "crm")]
EXC = ["TimeoutError", "ConnectionError", "KeyError", "ValueError", "PermissionError", "FileNotFoundError"]
OSERR = {"TimeoutError", "ConnectionError", "PermissionError", "FileNotFoundError"}
RULES = [
    ("return et is TimeoutError", lambda e: e == "TimeoutError", "подавляется только ровно TimeoutError"),
    ("return et is not None and issubclass(et, OSError)", lambda e: e in OSERR,
     "подавляются подклассы OSError: TimeoutError, ConnectionError, PermissionError, FileNotFoundError"),
    ("return isinstance(ev, (TimeoutError, ConnectionError))", lambda e: e in ("TimeoutError", "ConnectionError"),
     "подавляются TimeoutError и ConnectionError"),
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, px = rng.choice(CTX)
    rule_txt, supp, rule_note = rng.choice(RULES)
    for _ in range(300):
        n = rng.randint(3, 4)
        hosts = [f"{px}{i}" for i in rng.sample(range(1, 10), n)]
        fail = {h: rng.choice(EXC) for h in hosts if rng.random() < 0.6}
        kinds = ["none" if h not in fail else ("supp" if supp(fail[h]) else "prop") for h in hosts]
        if {"none", "supp", "prop"} <= set(kinds):
            break
    else:
        raise RuntimeError("t21_exit_suppress: не подобран набор")
    fail_txt = ", ".join(f'"{h}": {fail[h]}' for h in hosts if h in fail)
    lines = ["class Drain:",
             "    def __init__(self, host):",
             "        self.host = host",
             "    def __enter__(self):",
             '        print("drain", self.host)',
             "    def __exit__(self, et, ev, tb):",
             '        print("undrain", self.host, et.__name__ if et else "-")',
             f"        {rule_txt}",
             "",
             f"fail = {{{fail_txt}}}",
             f"for host in {hosts!r}:",
             "    try:",
             "        with Drain(host):",
             "            if host in fail: raise fail[host](host)",
             '            print("patched", host)',
             '        print("back", host)',
             "    except Exception as e:",
             '        print("failed", host, type(e).__name__)']
    code = "\n".join(lines)
    outs, notes = [], []
    for h, kind in zip(hosts, kinds):
        outs.append(f"drain {h}")
        if kind == "none":
            outs += [f"patched {h}", f"undrain {h} -", f"back {h}"]
            notes.append(f"{h}: без исключения — patched, undrain с «-», back")
        elif kind == "supp":
            outs += [f"undrain {h} {fail[h]}", f"back {h}"]
            notes.append(f"{h}: {fail[h]} подавлен __exit__ — «patched» пропущен, но «back» печатается")
        else:
            outs += [f"undrain {h} {fail[h]}", f"failed {h} {fail[h]}"]
            notes.append(f"{h}: {fail[h]} не подавлен — уходит во внешний except, «back» не печатается")
    out = "\n".join(outs)
    expl = (f"__exit__ вызывается при выходе из with всегда и печатает тип исключения; {rule_note}. "
            + "; ".join(notes) + ". Вывод по строкам: " + " / ".join(f"«{x}»" for x in outs) + ".")
    stem = f"Скрипт обслуживания ({ctx}) по очереди выводит узлы из балансировки, патчит и возвращает их."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"rule": rule_txt, "fail": fail, "hosts": hosts}, language="python")
