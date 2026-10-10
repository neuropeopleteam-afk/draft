#!/usr/bin/env python3
"""Прогон нагрузки по сценариям жюри (tools/loadtest/jury_load.py) и сводка для docs/LOAD.md (Я7, 09.10).

  run_load.py prepare --host URL                 # одна новая песочница жюри → /tmp/lt_jury_state.json
  run_load.py run --host URL -u 100 -r 2 -t 10m --tag stand_100 [--server-stats] [--xlink-file F]
  run_load.py summary --tag stand_100            # таблица p50/p95/p99 + ресурсы сервера → stdout (markdown)
  run_load.py burst --host URL -n 5 --tag stand_burst   # холодный вход N экспертов одновременно (новые песочницы)
  run_load.py cleanup --host URL                 # удалить песочницы прогона (DELETE /api/jury/sandbox токеном персоны)
  run_load.py preflight --host URL --xlink-file F   # перед прогоном: стенд жив, LLM, личная ссылка, Locust, сервер
  run_load.py nginx --tag stand_100              # сверка с журналом nginx стенда: сколько запросов дошло, коды ответа
  В run: --burst-at 300 --burst-n 5 — тот же всплеск на 300-й секунде под нагрузкой.
  Все запросы подписаны User-Agent «spectrek-load/<tag>» (всплеск — «spectrek-load/<tag>-burst»).

Только стандартная библиотека; Locust — в отдельном окружении (LOCUST, по умолчанию /tmp/lt/bin/locust):
python3.12 -m venv /tmp/lt && /tmp/lt/bin/pip install locust==2.46.0.
--server-stats, nginx, preflight — команды на сервере стенда (только чтение) через SSH-обёртку: KPY — путь к ней
(вызов `python3 $KPY cmd '<команда>'`; без KPY эти шаги пропускаются). Результаты — docs/loadtest/<tag>_stats.csv, _stats_history.csv,
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
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "loadtest"
STATE = Path(os.environ.get("LT_STATE", "/tmp/lt_jury_state.json"))
LOCUST = os.environ.get("LOCUST", "/tmp/lt/bin/locust")
KPY = os.environ.get("KPY", "")
NGINX_LOG_DIR = os.environ.get("LT_NGINX_LOG_DIR", "/var/log/nginx")  # журнал nginx хоста стенда (формат combined)
UA = "spectrek-load/prepare"  # User-Agent запросов этого скрипта; run и burst ставят свой тег


def _remote(script: str, timeout: int = 120) -> str:
    """Команда на сервере стенда через SSH-обёртку (только чтение). Без KPY — пустая строка."""
    if not KPY:
        return ""
    p = subprocess.run([sys.executable, KPY, "cmd", script], capture_output=True, text=True, timeout=timeout)
    return p.stdout + p.stderr


def _post(url: str, body: dict | None, token: str | None = None, method: str = "POST") -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"content-type": "application/json", "user-agent": UA,
                                          **({"authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def _get(url: str) -> tuple[int, str, dict]:
    req = urllib.request.Request(url, headers={"user-agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode(errors="replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, "", dict(e.headers)


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
    for sid in [x for x in (st.get("scenario"), *st.get("burst_sids", [])) if x]:  # после одного burst — без основной
        try:
            tok = _post(f"{a.host}/api/jury/login", {"persona": "employer", "scenario": sid})["access_token"]
            d = _post(f"{a.host}/api/jury/sandbox", None, tok, method="DELETE")
            print(f"Песочница удалена: учёток {d.get('deleted_users')}, {d.get('seconds')} с")
        except Exception as e:  # noqa: BLE001
            print(f"Песочница не удалена: {type(e).__name__} — удалить вручную (администратор стенда)")
    st["burst_sids"] = []
    STATE.write_text(json.dumps(st))


BURST_PERSONAS = ["employer", "candidate", "candidate_new", "expert", "candidate_nofsp", "fsp", "candidate_junior"]


def burst(a, tag: str | None = None) -> list[dict]:
    """Холодный вход N экспертов одновременно: каждый — «Войти» на главной (scenario=new → своя песочница; первая
    берёт запасную, остальные создаются сразу) и первые запросы кабинета. Время — с точки зрения эксперта."""
    global UA
    UA = f"spectrek-load/{tag or a.tag}-burst"
    res: list[dict] = [{} for _ in range(a.n)]
    go = threading.Event()

    def one(i: int) -> None:
        go.wait()
        t0 = time.time()
        try:
            d = _post(f"{a.host}/api/jury/login", {"persona": BURST_PERSONAS[i % len(BURST_PERSONAS)], "scenario": "new"})
            t1 = time.time()
            for path in ("/api/meta", "/api/jury/status"):
                c, _, _ = _get(f"{a.host}{path}")
                if c != 200:
                    raise RuntimeError(f"{path}: {c}")
            res[i] = {"persona": BURST_PERSONAS[i % len(BURST_PERSONAS)], "login_s": round(t1 - t0, 2),
                      "first_screen_s": round(time.time() - t0, 2), "created": bool(d.get("created")),
                      "shared": bool(d.get("shared")), "_sid": d.get("scenario")}
        except Exception as e:  # noqa: BLE001
            res[i] = {"error": f"{type(e).__name__}: {str(e)[:100]}", "login_s": round(time.time() - t0, 2)}

    ts = [threading.Thread(target=one, args=(i,)) for i in range(a.n)]
    for t in ts:
        t.start()
    go.set()
    for t in ts:
        t.join(timeout=300)
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    st["burst_sids"] = st.get("burst_sids", []) + [r.pop("_sid") for r in res if r.get("_sid")]
    STATE.write_text(json.dumps(st))
    OUT.mkdir(parents=True, exist_ok=True)
    out = {"n": a.n, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "results": res}
    (OUT / f"{tag or a.tag}_burst.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    ok = [r for r in res if "error" not in r]
    if ok:
        print(f"Всплеск {a.n}: вход {min(r['login_s'] for r in ok)}–{max(r['login_s'] for r in ok)} с, первый экран до "
              f"{max(r['first_screen_s'] for r in ok)} с; новых песочниц {sum(r['created'] for r in ok)}, общее демо "
              f"{sum(r['shared'] for r in ok)}, ошибок {a.n - len(ok)}")
    return res


def _server_stats(seconds: int, out: Path) -> None:
    """Цикл замеров на сервере одной SSH-сессией (только чтение): docker stats стека и load average."""
    n = max(1, seconds // 10)
    cg = "/sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' spectrek_fsp-api-1).scope"
    script = (f"echo '## memory.events api до'; grep -E '^(oom|oom_kill) ' {cg}/memory.events; "
              f"for i in $(seq {n}); do echo \"## $(date +%T) $(cut -d' ' -f1-3 /proc/loadavg)\"; "
              "docker stats --no-stream --format '{{.Name}};{{.CPUPerc}};{{.MemUsage}}' | grep '^spectrek_fsp-'; "
              "sleep 8; done; echo '## memory.peak api'; "
              f"cat {cg}/memory.peak; grep -E '^(oom|oom_kill) ' {cg}/memory.events")
    out.write_text(_remote(script, timeout=seconds + 300) or "KPY не задан — ресурсы сервера не сняты\n")


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
    env = {**os.environ, "LT_SCENARIO": st["scenario"], "LT_TAG": a.tag}
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
    if a.burst_at:
        b = argparse.Namespace(host=a.host, n=a.burst_n, tag=a.tag)
        threads.append(threading.Timer(a.burst_at, burst, args=(b,)))
        threads[-1].start()
    t0 = time.time()
    meta = {"tag": a.tag, "host": a.host, "users": a.users, "ramp_per_s": a.ramp, "time": a.time,
            "burst_at_s": a.burst_at, "burst_n": a.burst_n if a.burst_at else 0, "user_agent": f"spectrek-load/{a.tag}",
            "start": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    p = subprocess.run(cmd, env=env, cwd=ROOT, capture_output=True, text=True)
    (OUT / f"{a.tag}_locust.log").write_text(_scrub(p.stdout[-20000:] + "\n" + p.stderr[-20000:]))
    stop.set()
    for t in threads:
        t.join(timeout=dur + 400)
    meta.update(end=time.strftime("%Y-%m-%dT%H:%M:%S%z"), locust_exit=p.returncode)
    (OUT / f"{a.tag}_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
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
        txt = srv.read_text()
        if "## memory.events api до" in txt:
            print("События памяти api до прогона: " + " ".join(txt.split("## memory.events api до", 1)[1]
                                                               .split("##", 1)[0].split()))
        tail = txt.split("## memory.peak api", 1)
        if len(tail) == 2:
            v = tail[1].split()
            peak = f"{int(v[0]) / 2**20:.0f} МиБ" if v and v[0].isdigit() else "—"
            print(f"memory.peak api (с запуска контейнера): {peak}; события памяти после: " + " ".join(v[1:]))
    bf = OUT / f"{a.tag}_burst.json"
    if bf.exists():
        b = json.loads(bf.read_text())
        print(f"\nХолодный вход {b['n']} экспертов одновременно ({b['at']}):\n\n| Персона | Вход, с | Первый экран, с | "
              f"Новая песочница |\n|---|---:|---:|---|")
        for r in b["results"]:
            print(f"| {r.get('persona', '—')} | {r.get('login_s')} | {r.get('first_screen_s', '—')} | "
                  f"{'да' if r.get('created') else ('общее демо' if r.get('shared') else r.get('error', 'нет'))} |")
    cl = OUT / f"{a.tag}_client.txt"
    if cl.exists():
        vals = [float(x) for x in re.findall(r"locust_cpu=([\d.]+)%", cl.read_text())]
        las = [float(x.split()[0]) for x in re.findall(r"loadavg=([\d. ]+) locust", cl.read_text())]
        if vals:
            print(f"Машина теста: CPU Locust макс. {max(vals):.0f} %, load average макс. {max(las):.2f}")
    lg = OUT / f"{a.tag}_locust.log"
    if lg.exists():
        for ln in lg.read_text().splitlines():
            if ln.startswith("[jury_load]"):
                print("\nДействия за прогон (потолки LLM — docs/LOAD.md, раздел 3): " + ln.split("]", 1)[1].strip())
    ng = OUT / f"{a.tag}_nginx.txt"
    if ng.exists():
        print("\n" + ng.read_text().strip())


def _xlink_token(path: str) -> str:
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\s*JURY_LINK_\d+\s*=\s*(\S+)", line)
        if m:
            v = m.group(1).strip().strip("'\"")
            return v.split("/x/", 1)[1].strip("/") if "/x/" in v else v
    return ""


def preflight(a) -> None:
    """Перед прогоном на стенде: всё ли готово. Секреты не печатаются; на сервере — только чтение."""
    ok = True

    def line(good: bool, text: str) -> None:
        nonlocal ok
        ok = ok and good
        print(f"{'OK ' if good else 'ERR'} {text}")

    v = subprocess.run([LOCUST, "--version"], capture_output=True, text=True) if Path(LOCUST).exists() else None
    line(bool(v and v.returncode == 0), f"Locust: {(v.stdout or v.stderr).strip()[:60] if v else 'нет ' + LOCUST}")
    c, body, _ = _get(f"{a.host}/api/health")
    line(c == 200 and '"ok"' in body, f"/api/health: {c}")
    c, body, _ = _get(f"{a.host}/api/meta")
    if c == 200:
        llm = json.loads(body).get("llm", {})
        chain = ", ".join(f"{x.get('provider')}{'' if x.get('configured') else ' (не настроен)'}" for x in llm.get("chain", []))
        line(True, f"/api/meta: LLM {'вкл.' if llm.get('configured') else 'выкл.'}; цепочка: {chain or '—'}")
    else:
        line(False, f"/api/meta: {c}")
    if a.xlink_file:
        tok = _xlink_token(a.xlink_file) if Path(a.xlink_file).exists() else ""
        line(bool(tok), "личная ссылка: ключ JURY_LINK_1 в файле" + ("" if tok else " не найден"))
        if tok:
            req = urllib.request.Request(f"{a.host}/x/{tok}", headers={"user-agent": UA})

            class _NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs):
                    return None
            try:
                r = urllib.request.build_opener(_NoRedirect).open(req, timeout=30)
                code, hdr = r.status, str(r.headers)
            except urllib.error.HTTPError as e:
                code, hdr = e.code, str(e.headers)
            line(code in (200, 302, 303) and "fsp_x=" in hdr, f"вход по личной ссылке: {code}, cookie fsp_x "
                 f"{'есть' if 'fsp_x=' in hdr else 'нет'}")
    if KPY:
        out = _remote("cat /proc/loadavg; free -m | sed -n 2p; df -BG / | tail -1; "
                      "docker ps --format '{{.Names}} {{.Status}}' | grep '^spectrek_fsp-'; "
                      "docker inspect -f '{{.State.StartedAt}}' spectrek_fsp-api-1; "
                      "docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' spectrek_fsp-api-1 "
                      "| grep -E '^JURY_SPARE_SANDBOXES=' || echo 'JURY_SPARE_SANDBOXES не задан (по умолчанию 1)'; "
                      "echo deploying=$(pgrep -af 'deploy|docker compose (up|build)|docker-compose' | grep -vc pgrep)")
        print("Сервер стенда (только чтение):")
        for ln in out.strip().splitlines():
            print("   ", ln)
        m = re.search(r"^deploying=(\d+)", out, re.M)
        busy = int(m.group(1)) if m else -1
        line(busy == 0, f"выкладка или сборка на сервере: {'нет' if busy == 0 else ('идёт — подождать' if busy > 0 else 'не проверено')}")
    else:
        print("KPY не задан — сервер стенда не проверен")
    print("Готово к прогону" if ok else "Есть ошибки — прогон не начинать")
    sys.exit(0 if ok else 1)


def nginx(a) -> None:
    """Сверка с журналом nginx стенда (только чтение): сколько запросов с User-Agent прогона дошло до сервера, коды
    ответа, неуспешные — по началу пути. Печатаются только счётчики (без адресов, токенов и чужих строк)."""
    meta = json.loads((OUT / f"{a.tag}_meta.json").read_text()) if (OUT / f"{a.tag}_meta.json").exists() else {}
    ua = meta.get("user_agent", f"spectrek-load/{a.tag}")
    awk = ("awk '{st=$9; path=$7; sub(/\\?.*/, \"\", path); n=split(path, s, \"/\"); "
           "pre=(s[2]==\"x\") ? \"/x/<токен>\" : ((s[2]==\"api\") ? \"/\" s[2] \"/\" s[3] \"/\" s[4] : \"/\" s[2]); "
           "c[st]++; if (st !~ /^[23]/) f[st \" \" pre]++} END {for (k in c) print \"code\", k, c[k]; "
           "for (k in f) print \"fail\", k, f[k]}'")
    out = {}
    for kind, agent in (("main", ua), ("burst", ua + "-burst")):
        script = (f"cd {NGINX_LOG_DIR} && zcat -f access.log access.log.1 2>/dev/null | grep -aF '\"{agent}\"' | {awk}")
        out[kind] = _remote(script, timeout=300)
    lines = [f"# Журнал nginx стенда: запросы с User-Agent «{ua}» (всплеск — «{ua}-burst»)", ""]
    total = {}
    for kind, txt in out.items():
        codes = sorted((ln.split()[1], int(ln.split()[2])) for ln in txt.splitlines() if ln.startswith("code "))
        fails = sorted(((ln.split(" ", 1)[1].rsplit(" ", 1)[0], int(ln.rsplit(" ", 1)[1]))
                        for ln in txt.splitlines() if ln.startswith("fail ")), key=lambda x: -x[1])
        total[kind] = sum(n for _, n in codes)
        lines.append(f"{'Прогон' if kind == 'main' else 'Всплеск'}: строк журнала {total[kind]}; коды: "
                     + (", ".join(f"{c} — {n}" for c, n in codes) or "—"))
        for k, n in fails[:15]:
            lines.append(f"    {k}: {n}")
    st = OUT / f"{a.tag}_stats.csv"
    if st.exists():
        agg = next((r for r in csv.DictReader(open(st, encoding="utf-8")) if r["Name"] == "Aggregated"), None)
        fr = OUT / f"{a.tag}_failures.csv"
        zero = sum(int(r["Occurrences"]) for r in csv.DictReader(open(fr, encoding="utf-8"))
                   if re.search(r"\('0 |ConnectionError|RemoteDisconnected|Timeout|status_code=0", r["Error"])) \
            if fr.exists() else 0
        if agg:
            sent = int(agg["Request Count"])
            llm = sum(int(r["Request Count"]) for r in csv.DictReader(open(st, encoding="utf-8")) if r["Type"] == "LLM")
            lines.append(f"Locust: запросов {sent - llm} (без событий фоновой модели {llm}), из них без ответа (код 0, "
                         f"обрыв связи) {zero}; дошло до nginx {total.get('main', 0)} — разница "
                         f"{sent - llm - total.get('main', 0):+d}")
    (OUT / f"{a.tag}_nginx.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


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
    s.add_argument("--burst-at", type=int, default=0, help="секунда прогона для всплеска холодного входа (0 — без)")
    s.add_argument("--burst-n", type=int, default=5)
    s = sub.add_parser("burst")
    s.add_argument("--host", required=True)
    s.add_argument("-n", type=int, default=5)
    s.add_argument("--tag", required=True)
    for name in ("summary", "nginx"):
        s = sub.add_parser(name)
        s.add_argument("--tag", required=True)
    s = sub.add_parser("preflight")
    s.add_argument("--host", required=True)
    s.add_argument("--xlink-file", default="")
    a = ap.parse_args()
    {"prepare": prepare, "cleanup": cleanup, "run": run, "summary": summary, "burst": burst, "preflight": preflight,
     "nginx": nginx}[a.cmd](a)


if __name__ == "__main__":
    main()
