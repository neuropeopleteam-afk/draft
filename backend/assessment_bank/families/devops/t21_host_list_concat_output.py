"""devops.bash.t21_host_list_concat_output — predict_output (набор t21, порог Стажёра): простой for по словам
со счётчиком и склейкой строки в bash.

Скрипт перед выкладкой собирает список хостов в одну строку через разделитель и считает их. Ловушки чтения:
разделитель дописывается после КАЖДОГО хоста (в конце строки он тоже остаётся), а в части вариантов новый хост
приписывается в начало (`list="$h,$list"`) — порядок в строке обратный. Ключ — независимая модель склейки в
генераторе; проверка — исполнение показанного скрипта в bash-песочнице.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "devops.bash.t21_host_list_concat_output"

CTX = [("выкладка биллинга", ["bill"]), ("обновление каталога", ["cat"]), ("релиз платёжного шлюза", ["pay"]),
       ("перезапуск поиска", ["search", "idx"]), ("выкладка личного кабинета", ["lk"]),
       ("обновление очереди уведомлений", ["mq", "notify"]), ("релиз CRM", ["crm"])]
ROLES = ["web", "api", "db", "cache", "worker", "lb"]
SEPS = [",", ";", "|", "+"]
VARS = [("list", "n"), ("hosts", "count"), ("targets", "total"), ("line", "k")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, prefixes = rng.choice(CTX)
    lv, cv = rng.choice(VARS)
    k = rng.randint(3, 5)
    pool = [f"{rng.choice(prefixes)}-{r}{i}" for r in ROLES for i in (1, 2)]
    hosts = rng.sample(pool, k)
    sep = rng.choice(SEPS)
    prepend = rng.random() < 0.5
    start = rng.choice([0, 0, 1]) if not prepend else 0
    body = f'"$h{sep}${lv}"' if prepend else f'"${lv}$h{sep}"'
    code = (f'{lv}=""\n'
            f"{cv}={start}\n"
            f"for h in {' '.join(hosts)}; do\n"
            f"  {lv}={body}\n"
            f"  {cv}=$(({cv} + 1))\n"
            "done\n"
            f'echo "{cv}=${cv} {lv}=${lv}"')
    seq = list(reversed(hosts)) if prepend else hosts
    joined = "".join(h + sep for h in seq)
    total = start + k
    out = f"{cv}={total} {lv}={joined}"
    how = ("новый хост ставится В НАЧАЛО строки, поэтому порядок обратный" if prepend
           else "новый хост дописывается в конец строки, порядок как в списке")
    expl = (f"Цикл проходит {k} {plural(k, 'хост', 'хоста', 'хостов')}: {cv} растёт с {start} до {total}. В строке {lv} {how}, и после каждого хоста "
            f"стоит «{sep}» — последний разделитель тоже остаётся. Вывод: «{out}».")
    stem = f"Скрипт ({ctx}) собирает список хостов в одну строку и считает их перед выкладкой."
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"hosts": hosts, "prepend": prepend, "sep": sep}, language="bash")
