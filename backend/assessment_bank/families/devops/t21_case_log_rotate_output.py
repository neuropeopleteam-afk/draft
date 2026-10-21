"""devops.logs.t21_case_log_rotate_output — predict_output (набор t21, порог Junior): цикл по словам и `case`
с шаблонами имён в bash.

Скрипт ротации решает по имени файла лога, что с ним делать. Ловушки чтения: шаблон `case` должен совпасть со
ВСЕЙ строкой (`app.log.1` не подходит под `*.log`), срабатывает ПЕРВЫЙ подходящий шаблон сверху (`error.log.gz`
подходит и под `*.gz`, и под `*.log.*`), `a|b` — любой из шаблонов, `*` — всё остальное. Ключ — независимая модель
сопоставления (fnmatch по шаблонам по порядку) в генераторе; проверка — исполнение показанного скрипта в bash.
"""
from __future__ import annotations

from fnmatch import fnmatchcase

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.logs.t21_case_log_rotate_output"

CTX = [("логи биллинга", "billing"), ("логи API каталога", "catalog"), ("журналы платёжного шлюза", "gateway"),
       ("логи поиска", "search"), ("журналы личного кабинета", "cabinet"), ("логи CRM", "crm"),
       ("журналы очереди писем", "mailer")]
PATTERNS = ["*.gz", "*.log", "*.log.*", "error*", "*.tmp|*.swp", "access*", "*.[0-9]"]
ACTIONS = ["skip", "rotate", "compress", "alert", "delete", "archive", "keep"]


def _names(app: str) -> list[str]:
    return [f"{app}.log", f"{app}.log.1", f"{app}.log.2.gz", "error.log", "error.log.3", "error.log.1.gz",
            "access.log", "access.log.4", f"{app}.tmp", "core.swp", f"{app}.out", "access.gz", "gc.log.0"]


def _match(name: str, pats: list[str]) -> int:
    for i, p in enumerate(pats):
        if any(fnmatchcase(name, alt) for alt in p.split("|")):
            return i
    return len(pats)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, app = rng.choice(CTX)
    for _ in range(500):
        pats = rng.sample(PATTERNS, 3)
        acts = rng.sample(ACTIONS, 4)
        files = rng.sample(_names(app), rng.randint(4, 5))
        hits = [_match(f, pats) for f in files]
        # первый подходящий шаблон важен: хотя бы один файл подходит под два шаблона; есть и «остальные» (*)
        multi = any(sum(any(fnmatchcase(f, a) for a in p.split("|")) for p in pats) >= 2 for f in files)
        if multi and len(pats) in hits and len(set(hits)) >= 3:
            break
    else:
        raise RuntimeError("t21_case_log_rotate: не подобран набор")
    arms = [f"    {p}) echo \"{a} $f\" ;;" for p, a in zip(pats, acts)] + [f"    *) echo \"{acts[3]} $f\" ;;"]
    code = (f"for f in {' '.join(files)}; do\n"
            "  case $f in\n" + "\n".join(arms) + "\n"
            "  esac\n"
            "done")
    out_lines, notes = [], []
    for f, h in zip(files, hits):
        act = acts[h]
        out_lines.append(f"{act} {f}")
        all_hits = [pats[i] for i in range(3) if any(fnmatchcase(f, a) for a in pats[i].split("|"))]
        if h == 3:
            notes.append(f"{f} — ни один шаблон не совпал целиком → *")
        elif len(all_hits) > 1:
            notes.append(f"{f} подходит под {', '.join(all_hits)}, срабатывает первый — {pats[h]}")
        else:
            notes.append(f"{f} → {pats[h]}")
    out = "\n".join(out_lines)
    expl = ("Шаблон case сравнивается со всей строкой, срабатывает первый подходящий сверху. " + "; ".join(notes)
            + ". Вывод по строкам: " + " / ".join(f"«{x}»" for x in out_lines) + ".")
    stem = f"Скрипт ротации ({ctx}) решает по имени каждого файла, что с ним сделать."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"patterns": pats, "files": files}, language="bash")
