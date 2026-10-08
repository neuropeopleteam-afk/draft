"""common.docker.compose_port_bug — find_bug: опубликованный порт вместо порта контейнера внутри сети compose.

В docker-compose.yml сервисы обращаются друг к другу по имени сервиса. Внутри сети compose доступен порт,
который слушает процесс в контейнере (правая часть `ports: "хост:контейнер"`), а левая, опубликованная
часть относится только к хосту. Дефект: в переменной окружения одного сервиса адрес соседа указан с
опубликованным портом. Один подтип; варьируются стек, набор сервисов и портов, какой из адресов ошибочен
(web → api или api → db), порядок сервисов и служебные строки (healthcheck с localhost и портом контейнера —
правильная строка-ловушка, depends_on, restart). Ключ проверяется исполнением модели сети compose
(разбор показанного YAML и проверка каждого адреса `схема://сервис:порт`).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.docker.compose_port_bug"

# (контекст, образ/сборка api, порт контейнера api, образы БД: (имя, образ, порт, схема URL))
APIS = [("интернет-магазин", "./api", [3000, 5000, 8000]), ("сервис бронирования", "./backend", [8080, 9000, 5000]),
        ("трекер задач", "./server", [3000, 4000, 8000]), ("CRM", "./app", [8000, 8080, 5050])]
DBS = [("db", "postgres:16", 5432, "postgres://app:app@{host}:{port}/app"),
       ("db", "postgres:15-alpine", 5432, "postgresql://svc:svc@{host}:{port}/svc"),
       ("cache", "redis:7-alpine", 6379, "redis://{host}:{port}/0"),
       ("mongo", "mongo:7", 27017, "mongodb://{host}:{port}/app")]
HOST_PORTS = [8080, 8081, 8088, 9090, 18080, 3001]

MODEL = '''import re

COMPOSE = """{compose}"""


def parse(text):
    """Разбор подмножества YAML compose: services → сервис → ключи, списки строк, вложенный environment."""
    services, cur, key, env = {{}}, None, None, None
    for raw in text.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        ind = len(raw) - len(raw.lstrip())
        s = raw.strip()
        if ind == 2 and s.endswith(":"):
            cur = s[:-1]; services[cur] = {{}}; key = env = None
        elif ind == 4 and cur:
            k, _, v = s.partition(":")
            key = k.strip(); v = v.strip()
            services[cur][key] = v if v else None
        elif ind == 6 and cur and key:
            if s.startswith("- "):
                if not isinstance(services[cur][key], list):
                    services[cur][key] = []
                services[cur][key].append(s[2:].strip().strip('"'))
            else:
                if not isinstance(services[cur][key], dict):
                    services[cur][key] = {{}}
                k, _, v = s.partition(":")
                services[cur][key][k.strip()] = v.strip().strip('"')
    return services


def container_ports(svc):
    out = set()
    for m in svc.get("ports") or []:
        out.add(int(str(m).split(":")[-1]))
    for e in svc.get("expose") or []:
        out.add(int(e))
    return out


services = parse(COMPOSE)
ok = True
for name, svc in services.items():
    for var, val in (svc.get("environment") or {{}}).items():
        m = re.search(r"://(?:[^@/]*@)?([a-z][a-z0-9_-]*):(\\d+)", val)
        if m and m.group(1) in services:  # адрес соседа по сети compose: доступен только порт контейнера
            if int(m.group(2)) not in container_ports(services[m.group(1)]):
                ok = False
print("RESULT: PASS" if ok else "RESULT: FAIL")
'''


def _compose(api_port, api_host_port, db, db_host_port, web_port, web_host_port, bad, extras, order):
    db_name, db_image, db_port, url = db
    api_lines = ["  api:", "    build: ./api" if "api" in extras["build"] else f"    build: {extras['build']}",
                 "    ports:", f'      - "{api_host_port}:{api_port}"']
    if "restart" in extras:
        api_lines.insert(2, "    restart: unless-stopped")
    db_url = url.format(host=db_name, port=db_host_port if bad == "api" else db_port)
    api_lines += ["    environment:", f"      DATABASE_URL: {db_url}"]
    if "log" in extras:
        api_lines.append(f"      LOG_LEVEL: {extras['log']}")
    if "depends" in extras:
        api_lines += ["    depends_on:", f"      - {db_name}"]
    if "health" in extras:
        api_lines += ["    healthcheck:", f'      test: ["CMD", "curl", "-f", "http://localhost:{api_port}/health"]']
    web_lines = ["  web:", "    build: ./web", "    ports:", f'      - "{web_host_port}:{web_port}"',
                 "    environment:",
                 f"      API_URL: http://api:{api_host_port if bad == 'web' else api_port}"]
    if "depends" in extras:
        web_lines += ["    depends_on:", "      - api"]
    db_lines = [f"  {db_name}:", f"    image: {db_image}"]
    if db_host_port:
        db_lines += ["    ports:", f'      - "{db_host_port}:{db_port}"']
    else:
        db_lines += ["    expose:", f'      - "{db_port}"']
    blocks = {"api": api_lines, "web": web_lines, "db": db_lines}
    lines = ["services:"]
    for b in order:
        lines += blocks[b]
    return "\n".join(lines) + "\n"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, build, api_ports = rng.choice(APIS)
    api_port = rng.choice(api_ports)
    api_host_port = rng.choice([p for p in HOST_PORTS if p != api_port])
    db = rng.choice(DBS)
    db_host_port = rng.choice([db[2] + 1, db[2] + 10, db[2] + 1000, 15432 if db[2] == 5432 else db[2] + 2, None])
    web_port, web_host_port = rng.choice([(80, 80), (80, 8000), (3000, 3000), (5173, 8080)])
    bad = rng.choice(["web", "api"])
    if bad == "api" and db_host_port is None:  # для ошибки «порт хоста» у БД должен быть опубликованный порт
        db_host_port = db[2] + rng.choice([1, 10, 1000])
    extras = {"build": build}
    for k, v in (("restart", True), ("log", rng.choice(["info", "debug", "warning"])), ("depends", True),
                 ("health", True)):
        if rng.random() < 0.5:
            extras[k] = v
    order = rng.choice([["api", "web", "db"], ["web", "api", "db"], ["db", "api", "web"], ["api", "db", "web"]])
    buggy = _compose(api_port, api_host_port, db, db_host_port, web_port, web_host_port, bad, extras, order)
    fixed = _compose(api_port, api_host_port, db, db_host_port, web_port, web_host_port, None, extras, order)
    ch = changed_lines(buggy, fixed)
    assert len(ch) == 1, ch
    key = next(iter(ch))
    checks = [Check(name="buggy_fails", runner="python", program=MODEL.format(compose=buggy), expect="fail"),
              Check(name="fixed_passes", runner="python", program=MODEL.format(compose=fixed), expect="pass",
                    embeds_display_code=False)]
    if bad == "web":
        symptom = (f"Сайт открывается на `http://localhost:{web_host_port}`, но запросы к API из контейнера `web` "
                   f"завершаются `connection refused`; `curl http://localhost:{api_host_port}/health` с хоста отвечает.")
        why = (f"Строка {key}: `web` обращается к `api` по имени сервиса внутри сети compose, где доступен порт "
               f"контейнера {api_port}. Порт {api_host_port} — опубликованный на хосте, внутри сети его никто не "
               f"слушает. Нужно `http://api:{api_port}`.")
    else:
        symptom = (f"Контейнер `api` при старте не может подключиться к базе: `connection refused`; "
                   f"с хоста клиент к `localhost:{db_host_port}` подключается.")
        why = (f"Строка {key}: `api` обращается к `{db[0]}` внутри сети compose, где доступен порт контейнера "
               f"{db[2]}. Порт {db_host_port} опубликован только на хосте. Нужно `{db[0]}:{db[2]}`.")
    stem = (f"docker-compose.yml, {ctx}. {symptom} Укажите номер строки с ошибкой.")
    ak = AnswerKey(kind="line", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="published_port_in_network",
                         params={"fixed_code": fixed, "bad": bad})
