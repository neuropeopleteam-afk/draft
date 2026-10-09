#!/usr/bin/env python3
"""Прогон нагрузки по сценариям жюри (tools/loadtest/jury_load.py) и сводка для docs/LOAD.md (Я7, 09.10).

  run_load.py prepare --host URL                 # одна новая песочница жюри → /tmp/lt_jury_state.json
  run_load.py run --host URL -u 100 -r 2 -t 10m --tag stand_100 [--server-stats] [--xlink-file F]
  run_load.py summary --tag stand_100            # таблица p50/p95/p99 + ресурсы сервера → stdout (markdown)
  run_load.py cleanup --host URL                 # удалить песочницу (DELETE /api/jury/sandbox токеном её персоны)

Только стандартная библиотека; Locust — в отдельном окружении (LOCUST, по умолчанию /tmp/lt/bin/locust):
python3.12 -m venv /tmp/lt && /tmp/lt/bin/pip install locust==2.46.0.
--server-stats — замер `docker stats` на сервере «Москва» каждые ~10 с через tools/k.py (только чтение; на машине
с доступом к серверу; KPY — путь к k.py). Результаты — docs/loadtest/<tag>_stats.csv, _stats_history.csv,
_failures.csv, _server.txt, _client.txt. Пароли и токены не печатаются и не пишутся в файлы.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "loadtest"
STATE = Path(os.environ.get("LT_STATE", "/tmp/lt_jury_state.json"))
LOCUST = os.environ.get("LOCUST", "/tmp/lt/bin/locust")
KPY = os.environ.get("KPY", "/home/user/workspace/tools/k.py")


def _post(url: str, body: dict | None, token: str | None = None, method: str = "POST") -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"content-type": "application/json",
                                          **({"authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def prepare(a) -> None:
    t0 = time.time()
    d = _post(f"{a.host}/api/jury/login", {"persona": "employer", "scenario": "new"})
    sid = d.get("scenario")
    if not sid or not d.get("created"):
        sys.exit(f"Песочница не создана (лимит новых песочниц или общее демо): created={d.get('created')}")
    STATE.write_text(json.dumps({"host": a.host, "scenario": sid, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}))
    print(f"Песочница создана за {time.time() - t0:.1f} с; id — в {STATE} (в журналы не выводится)")


def cleanup(a) -> None:
    st = json.loads(STATE.read_text())
    tok = _post(f"{a.host}/api/jury/login", {"persona": "employer", "scenario": st["scenario"]})["access_token"]
    d = _post(f"{a.host}/api/jury/sandbox", None, tok, method="DELETE")
    print(f"Песочница удалена: учёток {d.get('deleted_users')}, {d.get('seconds')} с")


def _server_stats(seconds: int, out: Path) -> None:
    """Цикл замеров на сервере одной SSH-сессией (только чтение): docker stats стека и load average."""
    n = max(1, seconds // 10)
    script = (f"for i in $(seq {n}); do echo \"## $(date +%T) $(cut -d' ' -f1-3 /proc/loadavg)\"; "
              "docker stats --no-stream --format '{{.Name}};{{.CPUPerc}};{{.MemUsage}}' | grep '^spectrek_fsp-'; "
              "sleep 8; done; echo '## memory.peak api'; "
              "cat /sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' spectrek_fsp-api-1).scope/memory.peak; "
              "grep -E '^(oom|oom_kill) ' /sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' "
              "spectrek_fsp-api-1).scope/memory.events")
    with out.open("w") as f:
        subprocess.run([sys.executable, KPY, "cmd", script], stdout=f, stderr=subprocess.STDOUT, timeout=seconds + 300)


def _client_stats(seconds: int, out: Path, stop: threading.Event) -> None:
    """Нагрузка на машину теста: load average и CPU процесса Locust — чтобы не принять её за медленный сервер."""
    with out.open("w") as f:
        end = time.time() + seconds
        while time.time() < end and not stop.is_set():
            la = open("/proc/loadavg").read().split()[:3]
            cpu = subprocess.run(["sh", "-c", "ps -C locust -o %cpu= | awk '{s+=$1} END {print s+0}'"],
                                 capture_output=True, text=True).stdout.strip()
            f.write(f"{time.strftime('%T')} loadavg={' '.join(la)} locust_cpu={cpu}%\n")
            f.flush()
            stop.wait(10)


def _seconds(t: str) -> int:
    m = re.fullmatch(r"(\d+)([smh]?)", t)
    return int(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[m.group(2)]


def run(a) -> None:
    st = json.loads(STATE.read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "LT_SCENARIO": st["scenario"]}
    if a.xlink_file:
        env["LT_XLINK_FILE"] = a.xlink_file
    if a.web:
        env["LT_WEB"] = a.web
    dur = _seconds(a.time)
    stop = threading.Event()
    threads = [threading.Thread(target=_client_stats, args=(dur + 60, OUT / f"{a.tag}_client.txt", stop), daemon=True)]
    if a.server_stats:
        threads.append(threading.Thread(target=_server_stats, args=(dur + 30, OUT / f"{a.tag}_server.txt"), daemon=True))
    for t in threads:
        t.start()
    cmd = [LOCUST, "-f", str(ROOT / "tools/loadtest/jury_load.py"), "--host", a.host, "--headless", "-u", str(a.users),
           "-r", str(a.ramp), "-t", a.time, "--csv", str(OUT / a.tag), "--csv-full-history", "--only-summary",
           "--stop-timeout", "30", "--loglevel", "WARNING"] + (["--reset-stats"] if a.reset_stats else [])
    t0 = time.time()
    p = subprocess.run(cmd, env=env, cwd=ROOT, capture_output=True, text=True)
    (OUT / f"{a.tag}_locust.log").write_text(_scrub(p.stdout[-20000:] + "\n" + p.stderr[-20000:]))
    stop.set()
    for t in threads:
        t.join(timeout=dur + 400)
    print(f"Locust завершён (код {p.returncode}) за {time.time() - t0:.0f} с; CSV — docs/loadtest/{a.tag}_*.csv")


def _scrub(s: str) -> str:
    """На всякий случай: ни токен личной ссылки, ни JWT не уходят в файлы журнала."""
    s = re.sub(r"/x/[A-Za-z0-9_-]{8,}", "/x/<токен>", s)
    return re.sub(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "<jwt>", s)


def _mib(v: str) -> float:
    m = re.match(r"([\d.]+)\s*([KMG]i?B)", v.strip())
    if not m:
        return 0.0
    return float(m.group(1)) * {"KiB": 1 / 1024, "KB": 1 / 1024, "MiB": 1, "MB": 1, "GiB": 1024, "GB": 1024}[m.group(2)]


def summary(a) -> None:
    rows = list(csv.DictReader(open(OUT / f"{a.tag}_stats.csv", encoding="utf-8")))
    print(f"| Операция | Запросов | Ошибок | p50, мс | p95, мс | p99, мс | Макс., мс |\n|---|---:|---:|---:|---:|---:|---:|")
    agg = None
    for r in sorted(rows, key=lambda r: -int(r["Request Count"] or 0)):
        if r["Name"] == "Aggregated":
            agg = r
            continue
        print(f"| {r['Name']} | {int(r['Request Count'])} | {int(r['Failure Count'])} | {r['50%']} | {r['95%']} | "
              f"{r['99%']} | {float(r['Max Response Time']):.0f} |")
    if agg:
        print(f"| **Всего** | **{int(agg['Request Count'])}** | **{int(agg['Failure Count'])}** | **{agg['50%']}** | "
              f"**{agg['95%']}** | **{agg['99%']}** | **{float(agg['Max Response Time']):.0f}** |")
        print(f"\nЗапросов в секунду (средн.): {float(agg['Requests/s']):.1f}; доля ошибок: "
              f"{int(agg['Failure Count']) / max(1, int(agg['Request Count'])):.2%}")
    fails = OUT / f"{a.tag}_failures.csv"
    if fails.exists():
        fr = list(csv.DictReader(open(fails, encoding="utf-8")))
        if fr:
            print("\n| Операция | Ошибка | Число |\n|---|---|---:|")
            for r in sorted(fr, key=lambda r: -int(r["Occurrences"]))[:15]:
                print(f"| {r['Name']} | {_scrub(r['Error'])[:110]} | {r['Occurrences']} |")
    srv = OUT / f"{a.tag}_server.txt"
    if srv.exists():
        cpu: dict[str, list[float]] = {}
        mem: dict[str, list[float]] = {}
        la: list[float] = []
        for line in srv.read_text().splitlines():
            if line.startswith("## ") and re.match(r"## \d\d:\d\d:\d\d ", line):
                la.append(float(line.split()[2]))
            elif ";" in line:
                name, c, m = line.split(";")[:3]
                cpu.setdefault(name, []).append(float(c.rstrip("%") or 0))
                mem.setdefault(name, []).append(_mib(m.split("/")[0]))
        print(f"\nРесурсы сервера ({len(la)} замеров docker stats):\n\n| Контейнер | CPU макс. / средн., % одного ядра | "
              f"Память макс., МиБ |\n|---|---|---:|")
        for name in sorted(cpu):
            c = cpu[name]
            print(f"| {name} | {max(c):.0f} / {sum(c) / len(c):.0f} | {max(mem[name]):.0f} |")
        if la:
            print(f"\nLoad average сервера (1 мин): макс. {max(la):.2f}, средн. {sum(la) / len(la):.2f} (4 ядра)")
        tail = srv.read_text().split("## memory.peak api", 1)
        if len(tail) == 2:
            print("memory.peak api и события памяти: " + " ".join(tail[1].split()))
    cl = OUT / f"{a.tag}_client.txt"
    if cl.exists():
        vals = [float(x) for x in re.findall(r"locust_cpu=([\d.]+)%", cl.read_text())]
        las = [float(x.split()[0]) for x in re.findall(r"loadavg=([\d. ]+) locust", cl.read_text())]
        if vals:
            print(f"Машина теста: CPU Locust макс. {max(vals):.0f} %, load average макс. {max(las):.2f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("prepare", "cleanup"):
        s = sub.add_parser(name)
        s.add_argument("--host", required=True)
    s = sub.add_parser("run")
    s.add_argument("--host", required=True)
    s.add_argument("--web", default="", help="адрес страниц, если не совпадает с --host (локальный стенд)")
    s.add_argument("-u", "--users", type=int, default=100)
    s.add_argument("-r", "--ramp", type=float, default=2)
    s.add_argument("-t", "--time", default="10m")
    s.add_argument("--tag", required=True)
    s.add_argument("--xlink-file", default="")
    s.add_argument("--server-stats", action="store_true")
    s.add_argument("--reset-stats", action="store_true", help="сбросить статистику после разгона (Locust --reset-stats)")
    s = sub.add_parser("summary")
    s.add_argument("--tag", required=True)
    a = ap.parse_args()
    {"prepare": prepare, "cleanup": cleanup, "run": run, "summary": summary}[a.cmd](a)


if __name__ == "__main__":
    main()
