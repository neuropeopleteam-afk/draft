"""security.url.t21_url_host_split_output — predict_output (набор t21, порог Стажёра): разбор адреса через
`url.split("/")` — хост в `parts[2]` и длина списка `len(parts)`.

Перед сверкой со списком доверенных доменов программа делит каждый адрес по «/» и печатает элемент с индексом 2
(хост, иногда с портом) и число частей. Ловушки чтения: после «https:» между двумя «/» стоит пустая строка, поэтому
хост — третий элемент, а не второй; хвостовой «/» даёт ещё одну пустую строку в конце списка, и она тоже считается
в len. Адресов 2–3 — в цикле или по одному блоку на адрес. Ключ — независимая модель (список частей собирается из
схемы, хоста и сегментов пути, без split); проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.url.t21_url_host_split_output"

# (контекст, условие, хосты, сегменты пути)
CTX = [
    ("почтовый шлюз",
     "Почтовый шлюз перед доставкой письма сверяет ссылки из него со списком доверенных доменов; программа "
     "разбирает адреса ссылок.",
     ["lk.bank.test", "mail.corp.local", "pay.shop.example", "promo.shop.example", "id.portal.test",
      "secure-login.test:8443"],
     ["login", "reset", "promo", "unsubscribe", "track", "invoice"]),
    ("журнал прокси",
     "Скрипт аудита разбирает адреса из журнала корпоративного прокси перед сверкой с чёрным списком доменов.",
     ["cdn.files.example", "api.crm.local", "upload.share.test", "wiki.corp.local", "proxy.corp.local:3128",
      "dl.tools.example"],
     ["static", "v2", "download", "files", "img", "export"]),
    ("адрес возврата",
     "Сервис входа принимает адрес возврата (redirect_uri) только для зарегистрированных доменов; программа "
     "разбирает присланные адреса.",
     ["app.portal.test", "sso.corp.local", "m.portal.test", "partner.shop.example", "localhost:8080",
      "auth.portal.test"],
     ["callback", "oauth", "done", "auth", "return", "home"]),
    ("адрес вебхука",
     "Перед сохранением адреса вебхука сервис проверяет, не ведёт ли он во внутреннюю сеть; программа разбирает "
     "адреса из заявок.",
     ["hooks.crm.test", "10.0.0.12", "192.168.1.20:9000", "bot.chat.example", "ci.build.local",
      "notify.shop.example"],
     ["hook", "events", "api", "push", "ci", "deploy"]),
    ("отчёт сканера",
     "Сканер уязвимостей выгрузил найденные адреса, и скрипт собирает из них хосты для отчёта.",
     ["admin.cms.local", "test.shop.example", "old.portal.test", "backup.corp.local:8081", "dev.api.test",
      "stage.crm.local"],
     ["admin", "backup", "phpinfo", "debug", "config", "status"]),
]
NAMES = [("urls", "url", "parts"), ("links", "link", "p"), ("targets", "t", "chunks"), ("addrs", "a", "segs")]


def _url(rng, host: str, segs_pool: list[str], depth: int, trailing: bool):
    scheme = rng.choice(["https", "https", "http"])
    segs = rng.sample(segs_pool, depth)
    url = f"{scheme}://{host}" + "".join("/" + s for s in segs) + ("/" if trailing else "")
    parts = [scheme + ":", "", host] + segs + ([""] if trailing else [])  # независимая модель split("/")
    return url, parts


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, stem0, hosts_pool, segs_pool = rng.choice(CTX)
    unrolled = rng.random() < 0.35
    k = 2 if unrolled else rng.choice([2, 3, 3])
    for _ in range(200):
        shapes = [(rng.randint(0, 2), rng.random() < 0.45) for _ in range(k)]
        trails = [t for _d, t in shapes]
        lens = [3 + d + (1 if t else 0) for d, t in shapes]
        if any(trails) and not all(trails) and len(set(lens)) >= 2:
            break
    else:
        raise RuntimeError("t21_url_host_split: не собрались адреса")
    hosts = rng.sample(hosts_pool, k)
    items = [_url(rng, h, segs_pool, d, t) for h, (d, t) in zip(hosts, shapes)]
    host_first = rng.random() < 0.6
    lv, uv, pv = rng.choice(NAMES)
    pr = (lambda v: f"print({v}[2], len({v}))") if host_first else (lambda v: f"print(len({v}), {v}[2])")
    if unrolled:
        lines = []
        for url, _parts in items:
            lines += [f'{uv} = "{url}"', f'{pv} = {uv}.split("/")', pr(pv)]
        code = "\n".join(lines)
    else:
        lst = ", ".join(f'"{u}"' for u, _p in items)
        code = (f"{lv} = [{lst}]\n"
                f"for {uv} in {lv}:\n"
                f'    {pv} = {uv}.split("/")\n'
                f"    {pr(pv)}")
    out_lines = []
    trace = []
    for url, parts in items:
        host, n = parts[2], len(parts)
        out_lines.append(f"{host} {n}" if host_first else f"{n} {host}")
        trace.append(f"«{url}» → {parts!r} — {pv}[2] = '{host}', len = {n}")
    out = "\n".join(out_lines)
    port = "; порт остаётся частью хоста — «:» не разделитель" if any(":" in h for h in hosts) else ""
    expl = ("Разбор по «/»: " + "; ".join(trace) + ". Ловушки: между двумя «/» после «https:» (или «http:») стоит "
            "пустая строка, поэтому хост — элемент с индексом 2; хвостовой «/» добавляет в конец ещё одну пустую "
            f"строку, и len её тоже считает{port}. Вывод:\n" + out)
    return output_variant(FAMILY_ID, seed, stem=stem0, code=code, out=out, explanation=expl, context=ctx,
                          params={"urls": [u for u, _p in items], "unrolled": unrolled, "host_first": host_first},
                          language="python")
