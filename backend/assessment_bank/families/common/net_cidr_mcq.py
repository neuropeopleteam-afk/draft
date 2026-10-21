"""common.net.cidr_mcq — mcq_concept: адресация IPv4 и CIDR (маршрут, принадлежность,
число адресов, граница подсети).

Ключ генератор считает собственной битовой арифметикой; проверка в песочнице Python
независимо вычисляет ответ модулем ipaddress и сверяет его с текстом верного варианта.
"""
from __future__ import annotations

import json

from assessment_bank.gen_utils import build_variant, make_options, make_rng, pick_ranked, plural
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.net.cidr_mcq"

CTX = ["офисная сеть", "кластер Kubernetes", "VPC в облаке", "сеть дата-центра", "стенд QA",
       "VPN для сотрудников"]


def ip2i(s):
    a, b, c, d = (int(x) for x in s.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


def i2ip(n):
    return ".".join(str((n >> s) & 255) for s in (24, 16, 8, 0))


def net_of(ip, plen):
    mask = (0xFFFFFFFF << (32 - plen)) & 0xFFFFFFFF
    return ip & mask


def rnd_net(rng, plen):
    base = rng.choice([(10, None), (172, 16), (192, 168)])
    a = base[0]
    b = rng.randint(0, 255) if base[1] is None else (rng.randint(16, 31) if a == 172 else 168)
    ip = (a << 24) | (b << 16) | (rng.randint(0, 255) << 8) | rng.randint(0, 255)
    return net_of(ip, plen)


def q_route(rng):
    plens = sorted(rng.sample([8, 12, 16, 20, 22, 24, 26, 28], 3))
    dest = rnd_net(rng, 32)
    dest = (10 << 24) | (dest & 0x00FFFFFF)
    routes, gws = [], rng.sample(range(2, 250), 5)
    # вложенные префиксы, которые содержат или почти содержат адрес назначения
    for k, p in enumerate(plens):
        net = net_of(dest, p)
        if k == len(plens) - 1 and rng.random() < 0.5:
            net ^= 1 << (32 - p)  # самый длинный префикс — соседняя подсеть, не совпадает
        routes.append((net, p, f"10.255.0.{gws[k]}"))
    routes.append((0, 0, f"192.0.2.{gws[3]}"))
    rng.shuffle(routes)
    match = [r for r in routes if net_of(dest, r[1]) == r[0]]
    best = max(match, key=lambda r: r[1])
    code = "\n".join(("default" if p == 0 else f"{i2ip(n)}/{p}") + f" via {g} dev eth{j}"
                     for j, (n, p, g) in enumerate(routes))
    correct = f"Через {best[2]}"
    others = [f"Через {g}" for n, p, g in routes if g != best[2]]
    stem = f"Таблица маршрутизации (`ip route`). Через какой шлюз уйдёт пакет на {i2ip(dest)}?"
    expl = (f"Выбирается самый длинный совпадающий префикс: {i2ip(best[0])}/{best[1]}"
            if best[1] else "Ни один префикс не совпал — пакет уходит по маршруту по умолчанию")
    chk = (f"routes = {json.dumps([[('0.0.0.0/0' if p == 0 else f'{i2ip(n)}/{p}'), g] for n, p, g in routes])}\n"
           f"dst = ipaddress.ip_address('{i2ip(dest)}')\n"
           "cands = [(ipaddress.ip_network(r).prefixlen, g) for r, g in routes if dst in ipaddress.ip_network(r)]\n"
           "print('Через ' + max(cands)[1])\n")
    return stem, code, correct, others[:3], expl, chk


def q_member(rng):
    p = rng.choice([20, 21, 22, 23, 25, 26, 27])
    net = rnd_net(rng, p)
    size = 1 << (32 - p)
    inside = net + rng.randint(1, size - 2)
    outs = {net - rng.randint(1, 40), net + size + rng.randint(0, 40), net + size * 2 + rng.randint(1, 9)}
    flip = net ^ (1 << (32 - p))  # соседняя подсеть того же размера
    outs.add(flip + rng.randint(1, size - 2))
    outs = sorted(outs - {inside})
    code = f"allow {i2ip(net)}/{p};\ndeny all;"
    stem = "Фрагмент конфигурации nginx для служебного раздела. Запрос с какого адреса будет разрешён?"
    correct = i2ip(inside)
    others = [i2ip(x) for x in rng.sample(outs, 3)]
    expl = (f"Сеть {i2ip(net)}/{p} — это {size} {plural(size, 'адрес', 'адреса', 'адресов')}: {i2ip(net)}–{i2ip(net + size - 1)}")
    chk = (f"net = ipaddress.ip_network('{i2ip(net)}/{p}')\n"
           f"cands = {json.dumps([correct] + others)}\n"
           "print([c for c in cands if ipaddress.ip_address(c) in net][0])\n")
    return stem, code, correct, others, expl, chk


def q_hosts(rng):
    p = rng.choice([22, 23, 24, 25, 26, 27, 28, 29])
    net = rnd_net(rng, p)
    n = 1 << (32 - p)
    code = f"subnet: {i2ip(net)}/{p}\ngateway: {i2ip(net + 1)}"
    stem = ("Сколько адресов в этой подсети можно назначить узлам (включая шлюз), если адрес "
            "сети и широковещательный адрес не назначаются?")
    correct = str(n - 2)
    # ранг ключа равномерный (аудит 21.10: ключ почти всегда был «ближайшим к среднему»)
    pool = {"no_minus": n, "minus_one": n - 1, "bit_more": 2 * n - 2,
            "minus_gw": n - 3, "bit_less": n // 2 - 2, "bit_less_raw": n // 2}
    traps = pick_ranked(rng, n - 2, pool, rng.randrange(4))
    others = [str(pool[t]) for t in traps]
    expl = (f"При /{p} на номер узла остаётся {32 - p} {plural(32 - p, 'бит', 'бита', 'бит')}: "
            f"2^{32 - p} = {n} {plural(n, 'адрес', 'адреса', 'адресов')}, "
            f"минус адрес сети и широковещательный")
    chk = (f"net = ipaddress.ip_network('{i2ip(net)}/{p}')\n"
           "print(net.num_addresses - 2)\n")
    return stem, code, correct, others, expl, chk


def q_bounds(rng):
    p = rng.choice([20, 21, 22, 23, 25, 26, 27, 28])
    host = rnd_net(rng, 32)
    net = net_of(host, p)
    size = 1 << (32 - p)
    if host in (net, net + size - 1):
        host = net + size // 2 + 1
    code = f"address: {i2ip(host)}/{p}"
    stem = "Адрес интерфейса задан в CIDR-нотации. Каковы адрес сети и широковещательный адрес?"
    fmt = lambda a, b: f"сеть {i2ip(a)}, broadcast {i2ip(b)}"  # noqa: E731
    correct = fmt(net, net + size - 1)
    half = size // 2
    others = [fmt(net, net + size), fmt(net_of(host, p + 1), net_of(host, p + 1) + half - 1),
              fmt(net_of(host, p - 1), net_of(host, p - 1) + 2 * size - 1)]
    others = [o for o in others if o != correct][:3]
    expl = (f"Маска /{p} делит пространство на блоки по {size} {plural(size, 'адрес', 'адреса', 'адресов')}; адрес сети — начало "
            f"блока, broadcast — его последний адрес")
    chk = (f"net = ipaddress.ip_interface('{i2ip(host)}/{p}').network\n"
           "print(f'сеть {net.network_address}, broadcast {net.broadcast_address}')\n")
    return stem, code, correct, others, expl, chk


QUESTIONS = {"route": q_route, "member": q_member, "hosts": q_hosts, "bounds": q_bounds}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    for _ in range(50):
        qtype = rng.choice(sorted(QUESTIONS))
        stem, code, correct, others, expl, chk = QUESTIONS[qtype](rng)
        if len(set(others)) == 3 and correct not in others:
            break
    ctx = rng.choice(CTX)
    opts, key = make_options(rng, (correct, None), [(o, None) for o in others])
    checks = [Check(name="ipaddress", runner="python", program="import ipaddress\n" + chk,
                    expect="stdout_equals", expected_stdout=correct, embeds_display_code=False)]
    ak = AnswerKey(kind="option", value=key, explanation=expl + ".")
    return build_variant(FAMILY_ID, seed, stem=f"{ctx[0].upper() + ctx[1:]}. {stem}", code=code,
                         options=opts, answer_key=ak, context=ctx, verification="execution",
                         checks=checks, language="text", params={"qtype": qtype})
