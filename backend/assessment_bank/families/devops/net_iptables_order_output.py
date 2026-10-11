"""devops.net.iptables_order_output — predict_output: судьба пакетов по цепочке INPUT iptables (первое совпадение).

Правила задаются командами `iptables -P/-A/-I`: `-A` дописывает в конец цепочки, `-I INPUT N` вставляет на
позицию N (сдвигая остальные), действие — первое совпавшее правило, иначе политика цепочки (`-P`). Один подтип:
порядок правил с одной вставкой `-I`. Пакеты — новые TCP-соединения извне (не lo, не ESTABLISHED). Ключ
считает генератор, проверка — исполнение модели в песочнице Python, которая разбирает показанные команды
(модуль ipaddress для -s).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "devops.net.iptables_order_output"

CTX = ["бастион-хост", "сервер базы данных", "веб-сервер витрины", "сервер мониторинга", "узел очереди сообщений",
       "сервер CI-раннеров"]
SERVICES = {"ssh": 22, "https": 443, "http": 80, "postgres": 5432, "grafana": 3000, "node_exporter": 9100,
            "amqp": 5672}
NETS = ["10.0.0.0/8", "10.20.0.0/16", "192.168.10.0/24", "172.16.0.0/12", "10.20.30.0/24"]

MODEL = '''
import ipaddress, shlex

rules, policy = [], "ACCEPT"
for line in RULES.splitlines():
    a = shlex.split(line)
    if not a or a[0] != "iptables":
        continue
    if a[1] == "-P":
        policy = a[3]
        continue
    if a[1] == "-A":
        pos, rest = len(rules), a[3:]
    else:  # -I INPUT N
        pos, rest = int(a[3]) - 1, a[4:]
    r = {}
    i = 0
    while i < len(rest):
        r[rest[i]] = rest[i + 1]
        i += 2
    rules.insert(pos, r)


def verdict(src, port):
    for r in rules:
        if "-i" in r or "--ctstate" in r:
            continue  # пакеты условия — новые соединения извне: правила для lo и ESTABLISHED не совпадают
        if "-s" in r and ipaddress.ip_address(src) not in ipaddress.ip_network(r["-s"]):
            continue
        if "--dport" in r and int(r["--dport"]) != port:
            continue
        return r["-j"]
    return policy


for n, (src, port) in enumerate(PACKETS, 1):
    print(f"{n} {verdict(src, port)}")
'''


def _ip_in(rng, net):
    base, plen = net.split("/")
    a = [int(x) for x in base.split(".")]
    n = (a[0] << 24) | (a[1] << 16) | (a[2] << 8) | a[3]
    size = 1 << (32 - int(plen))
    x = n + rng.randint(1, min(size - 2, 250))
    return ".".join(str((x >> s) & 255) for s in (24, 16, 8, 0))


def _contains(net, ip):
    base, plen = net.split("/") if "/" in net else (net, "32")
    to_i = lambda s: sum(int(p) << sh for p, sh in zip(s.split("."), (24, 16, 8, 0)))  # noqa: E731
    mask = (0xFFFFFFFF << (32 - int(plen))) & 0xFFFFFFFF
    return (to_i(ip) & mask) == (to_i(base) & mask)


def _verdict(rules, policy, src, port):
    for r in rules:
        if r.get("iface") or r.get("state"):
            continue
        if r.get("src") and not _contains(r["src"], src):
            continue
        if r.get("port") is not None and r["port"] != port:
            continue
        return r["target"]
    return policy


def _cmd(r, insert_at=None):
    head = f"iptables -I INPUT {insert_at}" if insert_at else "iptables -A INPUT"
    if r.get("iface"):
        return f"{head} -i lo -j ACCEPT"
    if r.get("state"):
        return f"{head} -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT"
    parts = [head]
    if r.get("src"):
        parts.append(f"-s {r['src']}")
    if r.get("port") is not None:
        parts.append(f"-p tcp --dport {r['port']}")
    parts.append(f"-j {r['target']}")
    return " ".join(parts)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    for _ in range(1000):
        policy = rng.choice(["DROP", "DROP", "ACCEPT"])
        svc = rng.sample(sorted(SERVICES), 3)
        net, net2 = rng.sample(NETS, 2)
        appended = [{"iface": True}, {"state": True}]
        p0, p1, p2 = (SERVICES[s] for s in svc)
        appended.append({"src": net, "port": p0, "target": "ACCEPT"})
        appended.append({"port": p0, "target": rng.choice(["DROP", "REJECT"])})
        appended.append({"port": p1, "target": "ACCEPT"})
        appended.append({"src": net2, "port": p2, "target": "ACCEPT"})
        if policy == "ACCEPT":
            appended.append({"target": "DROP"})
        if rng.random() < 0.3:  # иногда общий запрет порта стоит раньше разрешения для сети
            appended[2], appended[3] = appended[3], appended[2]
        bad_ip = rng.choice([_ip_in(rng, net), f"203.0.113.{rng.randint(2, 250)}"])
        ins_rule = rng.choice([{"src": bad_ip, "target": "DROP"}, {"src": net, "port": p1, "target": "REJECT"},
                               {"port": p2, "target": "ACCEPT"}])
        ins_at = rng.randint(1, 3)
        rules = list(appended)
        rules.insert(ins_at - 1, ins_rule)
        pk = []
        cands = [(_ip_in(rng, net), p0), (f"198.51.100.{rng.randint(2, 250)}", p0), (bad_ip, p1),
                 (_ip_in(rng, net2), p2), (f"198.51.100.{rng.randint(2, 250)}", p2), (_ip_in(rng, net), p1),
                 (f"203.0.113.{rng.randint(2, 250)}", 8080)]
        pk = rng.sample(cands, 4)
        ans = [_verdict(rules, policy, s, p) for s, p in pk]
        ins_matters = ans != [_verdict(appended, policy, s, p) for s, p in pk]
        if len(set(ans)) >= 2 and ins_matters and len({s for s, _ in pk}) == 4:
            break
    lines = [f"iptables -P INPUT {policy}"] + [_cmd(r) for r in appended]
    lines.insert(rng.randint(len(lines) - 2, len(lines)), _cmd(ins_rule, ins_at))
    code = "\n".join(lines)
    expected = "\n".join(f"{i} {a}" for i, a in enumerate(ans, 1))
    plist = "\n".join(f"{i}. новое TCP-соединение с {s} на порт {p}" for i, (s, p) in enumerate(pk, 1))
    stem = (f"На сервере ({ctx}) цепочка INPUT пуста, затем по очереди выполнены команды ниже. Что произойдёт с "
            f"пакетами?\n{plist}\nОтвет — строки `номер ДЕЙСТВИЕ` (ACCEPT, DROP или REJECT).")
    expl = (f"-I INPUT {ins_at} вставляет правило на позицию {ins_at} — раньше правил, уже добавленных -A "
            "(последующие -A идут в конец); действует первое совпавшее правило, иначе политика -P. Правила для lo "
            "и ESTABLISHED к новым соединениям извне не относятся.")
    program = f'RULES = r"""{code}"""\nPACKETS = {pk!r}\n' + MODEL
    checks = [Check(name="stdout", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=expected)]
    ak = AnswerKey(kind="output", value=expected, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="bash",
                         display_code_note="Исполняется модель цепочки INPUT над показанными командами iptables",
                         params={"policy": policy, "insert_at": ins_at})
