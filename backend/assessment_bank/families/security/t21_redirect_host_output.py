"""security.web.t21_redirect_host_output — predict_output (набор t21, порог Senior): проверка адреса возврата
через `urllib.parse.urlsplit(url).hostname` и `endswith`.

После входа сервис решает, можно ли перенаправить пользователя по параметру `next`. Ловушки разбора: «//host/x»
без схемы — сетевой адрес (netloc есть, hostname — host); в «https://trusted@evil/» хост — после «@»; «#» обрывает
netloc («https://evil#@trusted/» → evil); порт отбрасывается, регистр приводится к нижнему; у относительного
«/profile» hostname — None. Проверка `endswith` — наивная (без точки, её обходит «nottrusted») или с точкой.
Ключ — независимая модель по формам адресов, которые выдаёт генератор (без urllib); проверка — исполнение
показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.web.t21_redirect_host_output"

CTX = ["портал единого входа", "онлайн-банк", "личный кабинет", "магазин", "сервис бронирования", "CRM"]
TRUSTED = ["shop.example", "bank.example", "id.example", "portal.example", "pay.example"]
EVIL = ["evil.test", "phish.example", "attacker.test", "x.test"]
PATHS = ["profile", "orders", "settings", "cart", "home"]


def _form(rng, kind: str, tr: str, ev: str) -> tuple[str, str | None, str]:
    """(адрес, hostname, пояснение) — hostname выводится из формы адреса, а не разбором."""
    p = rng.choice(PATHS)
    if kind == "relative":
        return f"/{p}", None, "относительный путь, netloc пуст"
    if kind == "netloc":
        return f"//{ev}/{p}", ev, "«//» без схемы — это сетевой адрес"
    if kind == "userinfo":
        return f"https://{tr}@{ev}/{p}", ev, "часть до «@» — имя пользователя"
    if kind == "suffix":
        return f"https://{tr}.{ev}/", f"{tr}.{ev}", "домен лишь начинается с доверенного"
    if kind == "concat":
        pre = rng.choice(["not", "my", "fake-"])
        return f"https://{pre}{tr}/{p}", f"{pre}{tr}", "другой домен, просто оканчивается теми же буквами"
    if kind == "port":
        return f"https://{tr.upper()}:8443/{p}", tr, "порт отброшен, регистр приведён к нижнему"
    if kind == "fragment":
        return f"https://{ev}#@{tr}/", ev, "«#» обрывает netloc"
    sub = rng.choice(["www", "login", "m"])
    return f"https://{sub}.{tr}/{p}", f"{sub}.{tr}", "поддомен доверенного"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    tr, ev = rng.choice(TRUSTED), rng.choice(EVIL)
    strict = rng.random() < 0.5
    k = rng.randint(3, 4)
    kinds = rng.sample(["netloc", "userinfo", "suffix", "concat", "port", "fragment"], k - 1)
    kinds.append(rng.choice(["relative", "sub"]))
    rng.shuffle(kinds)
    rows = [_form(rng, kind, tr, ev) for kind in kinds]
    cond = f'host == TRUSTED or host.endswith("." + TRUSTED)' if strict else "host.endswith(TRUSTED)"
    lit = ", ".join(f'"{u}"' for u, _h, _w in rows)
    code = ("from urllib.parse import urlsplit\n"
            f'TRUSTED = "{tr}"\n'
            f"targets = [{lit}]\n"
            "for url in targets:\n"
            "    host = urlsplit(url).hostname\n"
            "    if host is None:\n"
            '        verdict = "local"\n'
            f"    elif {cond}:\n"
            '        verdict = "allow"\n'
            "    else:\n"
            '        verdict = "block"\n'
            "    print(host, verdict)")
    lines, trace = [], []
    for url, host, why in rows:
        if host is None:
            verdict = "local"
        elif host == tr or host[-len(tr) - 1:] == "." + tr or (not strict and host[-len(tr):] == tr):
            verdict = "allow"
        else:
            verdict = "block"
        lines.append(f"{host} {verdict}")
        trace.append(f"{url} → hostname {host} ({why}) → {verdict}")
    out = "\n".join(lines)
    rule = ("проверка с точкой: равенство или «." + tr + "» в конце" if strict
            else "наивная проверка endswith без точки — её проходит любой домен, оканчивающийся на «" + tr + "»")
    expl = (f"Решение принимается по hostname из urlsplit; {rule}. " + "; ".join(trace) +
            f". Вывод: «{out.replace(chr(10), ' / ')}».")
    stem = (f"Вход в {ctx}: после авторизации сервис проверяет адрес возврата из параметра next и решает, "
            "можно ли на него перенаправить.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"trusted": tr, "kinds": kinds, "strict": strict}, language="python")
