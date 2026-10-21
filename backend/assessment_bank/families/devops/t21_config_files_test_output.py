"""devops.bash.t21_config_files_test_output — predict_output (набор t21, порог Junior): цикл по словам и
`if [ ! -f ] / elif [ ! -s ]` в bash.

Перед запуском сервиса скрипт проверяет файлы конфигурации в текущем каталоге: отсутствующий — «missing», пустой —
«empty», остальные считает. Ловушки чтения: `-f` ложно не только для отсутствующего файла, но и для КАТАЛОГА с
таким именем; пустой файл существует (`-f` истинно), его ловит только `-s`; ветки if/elif взаимоисключающие —
счётчик растёт только в else. Состав каталога дан в условии. Ключ — независимая модель проверок в генераторе;
проверка — исполнение показанного скрипта в bash-песочнице с теми же файлами.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "devops.bash.t21_config_files_test_output"

CTX = ["сервис биллинга", "API каталога", "платёжный шлюз", "индексатор поиска", "личный кабинет",
       "сервис уведомлений", "CRM"]
NAMES = ["app.conf", "db.conf", "cache.conf", "tls.pem", "secrets.env", "routes.yaml", "limits.conf", "conf.d",
         "certs", "logging.ini"]
LABELS = [("missing", "empty", "ok"), ("absent", "empty", "ready"), ("no", "zero", "good")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    miss, empty, okv = rng.choice(LABELS)
    for _ in range(300):
        k = rng.randint(4, 5)
        names = rng.sample(NAMES, k)
        kinds = {n: rng.choice(["full", "full", "empty", "absent", "dir"]) for n in names}
        ks = list(kinds.values())
        if ks.count("full") >= 1 and ks.count("empty") >= 1 and ("dir" in ks or "absent" in ks):
            break
    files: dict[str, str] = {}
    listing, absent = [], []
    for n in sorted(names):
        kind = kinds[n]
        if kind == "full":
            body = f"# {n}\nenabled=true\n"
            files[n] = body
            listing.append(f"файл `{n}` (2 строки)")
        elif kind == "empty":
            files[n] = ""
            listing.append(f"пустой файл `{n}`")
        elif kind == "dir":
            files[f"{n}/main.conf"] = "x=1\n"
            listing.append(f"каталог `{n}/` (внутри `main.conf`)")
        else:
            absent.append(f"`{n}`")
    code = (f"{okv}=0\n"
            f"for f in {' '.join(names)}; do\n"
            f'  if [ ! -f "$f" ]; then echo "{miss} $f"\n'
            f'  elif [ ! -s "$f" ]; then echo "{empty} $f"\n'
            f"  else {okv}=$(({okv} + 1))\n"
            "  fi\n"
            "done\n"
            f'echo "{okv}=${okv}"')
    out_lines, notes, cnt = [], [], 0
    for n in names:
        kind = kinds[n]
        if kind in ("absent", "dir"):
            out_lines.append(f"{miss} {n}")
            notes.append(f"`{n}` — " + ("каталог, а не обычный файл: `-f` ложно" if kind == "dir"
                                         else "нет в каталоге: `-f` ложно"))
        elif kind == "empty":
            out_lines.append(f"{empty} {n}")
            notes.append(f"`{n}` существует, но пуст: `-f` истинно, `-s` ложно")
        else:
            cnt += 1
            notes.append(f"`{n}` непустой — ветка else, счётчик +1")
    out_lines.append(f"{okv}={cnt}")
    out = "\n".join(out_lines)
    expl = ("; ".join(notes) + f". Счётчик растёт только в else: {okv}={cnt}. Вывод по строкам: "
            + " / ".join(f"«{x}»" for x in out_lines) + ".")
    stem = (f"Перед запуском ({ctx}) скрипт проверяет файлы конфигурации в текущем каталоге. В каталоге: "
            + "; ".join(listing) + (f"; нет {', '.join(absent)}." if absent else "; других файлов нет."))
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"kinds": kinds}, language="bash", files=files)
