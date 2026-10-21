"""security.net.t21_port_allowlist_js_output — predict_output (набор t21, порог Стажёра): цикл по попыткам
соединения, `if (!allowed.includes(port))` со счётчиком и запоминанием последнего заблокированного.

Сетевой фильтр проходит по массиву попыток `{ ip, port }`: если порта нет в списке разрешённых, увеличивает
счётчик и перезаписывает переменную «последний заблокированный». Ловушки чтения: отрицание `!` (считаются
НЕразрешённые порты), переменная хранит ПОСЛЕДНЕГО заблокированного (каждый следующий перезаписывает
предыдущего), а последняя попытка в массиве чаще всего разрешена. Ключ — независимый подсчёт в генераторе;
проверка — исполнение показанного кода в Node.js.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, plural

FAMILY_ID = "security.net.t21_port_allowlist_js_output"

CTX = ["шлюз офисной сети", "сервер базы данных", "бастион-хост", "кластер платёжного сервиса", "тестовый стенд",
       "сервер видеонаблюдения", "VPN-концентратор"]
ALLOWED = [[22, 443], [80, 443], [443, 8443], [22, 80, 443], [443, 5432], [53, 443, 8080], [22, 3000, 443],
           [25, 587, 993]]
DENY = [21, 23, 25, 135, 139, 445, 1433, 3306, 3389, 5900, 6379, 8080, 9200, 11211, 27017]
NAMES = [("allowed", "attempts", "blocked", "last"), ("openPorts", "conns", "denied", "lastDenied"),
         ("allowList", "events", "dropped", "lastDropped"), ("allowed", "requests", "rejected", "lastBad")]


def _ip(rng, net: str) -> str:
    if net == "10":
        return f"10.0.{rng.randint(0, 3)}.{rng.randint(2, 99)}"
    if net == "192":
        return f"192.168.0.{rng.randint(2, 99)}"
    return f"172.16.0.{rng.randint(2, 99)}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    av, xv, bv, lv = rng.choice(NAMES)
    allowed = rng.choice(ALLOWED)
    deny = [p for p in DENY if p not in allowed]
    net = rng.choice(["10", "192", "172"])
    for _ in range(200):
        n = rng.choice([4, 5, 5])
        n_bad = rng.randint(2, n - 2)
        ports = [rng.choice(deny) for _ in range(n_bad)] + [rng.choice(allowed) for _ in range(n - n_bad)]
        rng.shuffle(ports)
        if (ports[-1] in allowed) != (rng.random() < 0.7):
            continue
        ips = [_ip(rng, net) for _ in range(n)]
        if len(set(ips)) == n:
            break
    else:
        raise RuntimeError("t21_port_allowlist: не собрался список попыток")
    with_port = rng.random() < 0.5
    it = rng.choice(["a", "c", "conn"])
    rec = f'{it}.ip + ":" + {it}.port' if with_port else f"{it}.ip"
    lit = ", ".join(f'{{ ip: "{ip}", port: {p} }}' for ip, p in zip(ips, ports))
    loop = [f"for (const {it} of {xv}) {{",
            f"  if (!{av}.includes({it}.port)) {{ {bv}++; {lv} = {rec}; }}",
            "}"]
    code = "\n".join([f"const {av} = [{', '.join(map(str, allowed))}];",
                      f"const {xv} = [{lit}];",
                      f'let {bv} = 0, {lv} = "none";'] + loop +
                     [f'console.log("{bv}:", {bv});', f'console.log("last:", {lv});'])
    bad = [(ip, p) for ip, p in zip(ips, ports) if p not in allowed]
    lip, lp = bad[-1]
    last = f"{lip}:{lp}" if with_port else lip
    out = f"{bv}: {len(bad)}\nlast: {last}"
    tail_note = ("последняя попытка в массиве разрешена, поэтому в переменной остаётся более ранняя"
                 if ports[-1] in allowed else "последняя попытка массива сама заблокирована")
    expl = (f"Разрешены порты {', '.join(map(str, allowed))}; условие с ! срабатывает для остальных: "
            f"{', '.join(f'{ip}:{p}' for ip, p in bad)} — {len(bad)} "
            f"{plural(len(bad), 'попытка', 'попытки', 'попыток')}. "
            f"Каждая заблокированная перезаписывает {lv}, остаётся последняя из них ({tail_note}): «{last}». "
            f"Вывод: «{bv}: {len(bad)}», «last: {last}».")
    stem = (f"Сетевой фильтр ({ctx}): программа проверяет входящие соединения по списку разрешённых портов "
            "и запоминает последнее заблокированное.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"allowed": allowed, "ports": ports, "with_port": with_port}, language="javascript")
