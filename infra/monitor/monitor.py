#!/usr/bin/env python3
"""Мониторинг стенда «Драфт»: доступность, Yandex AI Studio, диск, контейнеры, резервные копии → письмо владельцу.

Запуск — systemd timer раз в 5 минут (spectrek-monitor.timer). Только стандартная библиотека Python 3.10+ (на хосте нет
boto3): письмо уходит через Yandex Cloud Postbox (API SESv2 SendEmail) с подписью AWS SigV4, ключи — те же, что у
приложения (/opt/spectrek_fsp/secrets/postbox.env).

Проверки (каждая — ok/fail и короткий текст):
* site     — GET {BASE}/api/health отвечает 200 и status=ok (API и БД живы);
* web      — GET {BASE}/ отвечает 200 или 401 (nginx и фронтенд, basic auth стенда не считается ошибкой);
* jury     — GET {BASE}/j/monitor открыт без пароля (QR живой демонстрации), если MONITOR_CHECK_JURY_LIVE=1;
* llm      — Yandex AI Studio отвечает на минимальный запрос (раз в MONITOR_LLM_EVERY_S, по умолчанию час): 401/403 —
             ключ или права (06.10 был 403), 429 — квота; текст запроса без ПДн;
* disk     — занято на / не больше MONITOR_DISK_MAX_PCT (90 %);
* docker   — контейнеры api, db, web запущены, без OOM; память api не выше MONITOR_MEM_MAX_PCT (90 %) лимита;
* backup   — свежая копия БД в /opt/spectrek_fsp/backups/db не старше MONITOR_BACKUP_MAX_H (30 ч).

Письмо — при переходе в «сбой» (MONITOR_FAILS подряд, по умолчанию 2 — разовый тайм-аут не будит владельца),
напоминание раз в MONITOR_REMIND_H часов, пока сбой не прошёл, и письмо «восстановлено». Состояние — в
MONITOR_STATE (JSON). Ключи и пароли в письмо и журнал не попадают.

    python3 monitor.py            # одна проверка (так вызывает таймер)
    python3 monitor.py --print    # проверить и показать итог, без писем и без записи состояния (MONITOR_TO не нужен)
    python3 monitor.py --test-mail  # отправить пробное письмо (проверка ключей Postbox и адреса)
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

DEFAULTS = {
    "MONITOR_BASE_URL": "https://fsp.neuropeople.pro",
    "MONITOR_TO": "",
    "MONITOR_FROM": "",
    "MONITOR_ENV_FILES": "/opt/spectrek_fsp/secrets/postbox.env,/opt/spectrek_fsp/secrets/llm.env",
    "MONITOR_STATE": "/var/lib/spectrek-monitor/state.json",
    "MONITOR_FAILS": "2",
    "MONITOR_REMIND_H": "6",
    "MONITOR_LLM_EVERY_S": "3600",
    "MONITOR_DISK_PATH": "/",
    "MONITOR_DISK_MAX_PCT": "90",
    "MONITOR_MEM_MAX_PCT": "90",
    "MONITOR_CONTAINERS": "spectrek_fsp-api-1,spectrek_fsp-db-1,spectrek_fsp-web-1",
    "MONITOR_BACKUP_DIR": "/opt/spectrek_fsp/backups/db",
    "MONITOR_BACKUP_MAX_H": "30",
    "MONITOR_CHECK_JURY_LIVE": "0",
    "MONITOR_TIMEOUT_S": "15",
}
UA = "spectrek-monitor/1.0"


# ------------------------------------------------------------------ настройки

def load_env_file(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def config(environ: dict[str, str] | None = None) -> dict[str, str]:
    """MONITOR_* из окружения (EnvironmentFile юнита) поверх значений по умолчанию; ключи Postbox и LLM — из файлов
    секретов приложения (окружение важнее — так удобно в тестах)."""
    env = dict(environ if environ is not None else os.environ)
    cfg = {k: env.get(k, v) for k, v in DEFAULTS.items()}
    for f in filter(None, (x.strip() for x in cfg["MONITOR_ENV_FILES"].split(","))):
        for k, v in load_env_file(f).items():
            cfg.setdefault(k, v)
    for k, v in env.items():
        if k.startswith(("POSTBOX_", "LLM_", "MAIL_")):
            cfg[k] = v
    cfg["MONITOR_FROM"] = cfg["MONITOR_FROM"] or cfg.get("MAIL_FROM") or "noreply@neuropeople.pro"
    return cfg


# ------------------------------------------------------------------ HTTP

def http(method: str, url: str, *, body: bytes | None = None, headers: dict | None = None,
         timeout: float = 15.0) -> tuple[int, bytes, float]:
    """(код, тело, секунды). Код 0 — нет соединения (DNS, тайм-аут, TLS)."""
    t = time.monotonic()
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — адреса из настроек
            return r.status, r.read(65536), time.monotonic() - t
    except urllib.error.HTTPError as e:
        return e.code, e.read(65536) if e.fp else b"", time.monotonic() - t
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        return 0, str(getattr(e, "reason", e)).encode()[:200], time.monotonic() - t


# ------------------------------------------------------------------ проверки

def check_site(cfg, h=http) -> tuple[bool, str]:
    code, body, dt = h("GET", cfg["MONITOR_BASE_URL"].rstrip("/") + "/api/health",
                       timeout=float(cfg["MONITOR_TIMEOUT_S"]))
    if code != 200:
        return False, f"/api/health: {'нет ответа (' + body.decode(errors='replace') + ')' if code == 0 else code}"
    try:
        d = json.loads(body)
    except ValueError:
        return False, "/api/health: ответ не JSON"
    if d.get("status") != "ok":
        return False, f"/api/health: status={d.get('status')}, db={d.get('db')}"
    return True, f"API и БД отвечают ({dt * 1000:.0f} мс)"


def check_web(cfg, h=http) -> tuple[bool, str]:
    code, body, dt = h("GET", cfg["MONITOR_BASE_URL"].rstrip("/") + "/", timeout=float(cfg["MONITOR_TIMEOUT_S"]))
    if code in (200, 401):
        return True, f"сайт отвечает {code} ({dt * 1000:.0f} мс)"
    return False, f"сайт: {'нет ответа' if code == 0 else code}"


def check_jury(cfg, h=http) -> tuple[bool, str]:
    code, _, _ = h("GET", cfg["MONITOR_BASE_URL"].rstrip("/") + "/j/monitor", timeout=float(cfg["MONITOR_TIMEOUT_S"]))
    if code == 200:
        return True, "страница QR /j/… открыта без пароля"
    return False, f"/j/…: {code or 'нет ответа'} (без пароля должна открываться — фрагмент nginx jury-live)"


def check_llm(cfg, h=http) -> tuple[bool, str]:
    base, key, model = cfg.get("LLM_BASE_URL"), cfg.get("LLM_API_KEY"), cfg.get("LLM_MODEL")
    if not (base and key and model):
        return True, "LLM не настроен — проверка пропущена"
    provider = (cfg.get("LLM_PROVIDER") or "").lower()
    folder = cfg.get("LLM_FOLDER_ID") or ""
    headers = {"Content-Type": "application/json"}
    if provider == "yandex_ai_studio":
        headers["Authorization"] = f"Api-Key {key}"
        if folder:
            headers["OpenAI-Project"] = folder
        if not model.startswith(("gpt://", "emb://")) and folder:
            model = f"gpt://{folder}/{model}"
    else:
        headers["Authorization"] = f"Bearer {key}"
    body = json.dumps({"model": model, "max_tokens": 5, "temperature": 0,
                       "messages": [{"role": "user", "content": "Ответь одним словом: да"}]}).encode()
    code, resp, dt = h("POST", base.rstrip("/") + "/chat/completions", body=body, headers=headers, timeout=40.0)
    if code == 200:
        return True, f"Yandex AI Studio отвечает ({dt:.1f} с)"
    hint = {401: "ключ API недействителен", 403: "нет прав у сервисного аккаунта или каталога (ai.languageModels.user)",
            404: "модель или адрес не найдены", 429: "превышена квота"}.get(code, "")
    return False, f"Yandex AI Studio: {code or 'нет ответа'}{' — ' + hint if hint else ''}"


def check_disk(cfg, du=shutil.disk_usage) -> tuple[bool, str]:
    u = du(cfg["MONITOR_DISK_PATH"])
    pct = u.used / u.total * 100 if u.total else 0
    free_gb = u.free / 1024 ** 3
    ok = pct <= float(cfg["MONITOR_DISK_MAX_PCT"])
    return ok, f"диск {cfg['MONITOR_DISK_PATH']}: занято {pct:.0f} %, свободно {free_gb:.1f} ГБ"


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False).stdout.strip()


def check_docker(cfg, run=_run) -> tuple[bool, str]:
    names = [x.strip() for x in cfg["MONITOR_CONTAINERS"].split(",") if x.strip()]
    if not names:
        return True, "контейнеры не заданы"
    fmt = "{{.Name}}|{{.State.Running}}|{{.State.OOMKilled}}|{{.RestartCount}}|{{.HostConfig.Memory}}"
    try:
        out = run(["docker", "inspect", "-f", fmt, *names])
    except FileNotFoundError:
        return False, "команда docker не найдена (мониторинг запущен не на сервере стенда?)"
    seen, bad, notes = {}, [], []
    for line in out.splitlines():
        p = line.strip().lstrip("/").split("|")
        if len(p) == 5:
            seen[p[0]] = p
    for n in names:
        p = seen.get(n)
        if p is None:
            bad.append(f"{n}: нет контейнера")
        elif p[1] != "true":
            bad.append(f"{n}: остановлен")
        elif p[2] == "true":
            bad.append(f"{n}: убит по памяти (OOM)")
    api = next((n for n in names if "-api-" in n), None)
    if api and api in seen and seen[api][1] == "true" and int(seen[api][4] or 0) > 0:
        stats = run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", api])
        used = _bytes(stats.split("/")[0]) if stats else None
        limit = int(seen[api][4])
        if used is not None:
            pct = used / limit * 100
            notes.append(f"память api {used / 1024 ** 2:.0f} из {limit / 1024 ** 2:.0f} МБ ({pct:.0f} %)")
            if pct > float(cfg["MONITOR_MEM_MAX_PCT"]):
                bad.append(f"api: память {pct:.0f} % лимита")
    if bad:
        return False, "; ".join(bad + notes)
    return True, "контейнеры запущены" + (", " + notes[0] if notes else "")


def _bytes(s: str) -> float | None:
    s = s.strip().replace(" ", "")
    units = {"KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3, "kB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3, "B": 1}
    for u, m in units.items():
        if s.endswith(u):
            try:
                return float(s[: -len(u)]) * m
            except ValueError:
                return None
    return None


def check_backup(cfg, now: float | None = None) -> tuple[bool, str]:
    d = Path(cfg["MONITOR_BACKUP_DIR"])
    files = sorted(d.glob("*.sql.gz"), key=lambda p: p.stat().st_mtime) if d.is_dir() else []
    if not files:
        return False, f"нет резервных копий в {d}"
    age_h = ((now or time.time()) - files[-1].stat().st_mtime) / 3600
    ok = age_h <= float(cfg["MONITOR_BACKUP_MAX_H"]) and files[-1].stat().st_size > 1024
    return ok, f"последняя копия БД {age_h:.0f} ч назад ({files[-1].stat().st_size / 1024 ** 2:.1f} МБ)"


CHECKS = {"site": ("Сайт и API", check_site), "web": ("Фронтенд", check_web), "jury": ("QR без пароля", check_jury),
          "llm": ("Yandex AI Studio", check_llm), "disk": ("Диск", check_disk), "docker": ("Контейнеры", check_docker),
          "backup": ("Резервная копия", check_backup)}


def run_checks(cfg, state: dict, now: float, checks=None) -> dict[str, tuple[bool, str]]:
    checks = checks or CHECKS
    out = {}
    for name, (_, fn) in checks.items():
        if name == "jury" and cfg["MONITOR_CHECK_JURY_LIVE"] != "1":
            continue
        if name == "llm":  # платный вызов — не чаще раза в MONITOR_LLM_EVERY_S, между ними — прошлый итог
            prev = state.get("checks", {}).get("llm")
            if prev and now - prev.get("checked_at", 0) < float(cfg["MONITOR_LLM_EVERY_S"]):
                out[name] = (prev["ok"], prev["text"])
                continue
        try:
            out[name] = fn(cfg)
        except Exception as e:  # noqa: BLE001 — сама проверка не должна ронять монитор
            out[name] = (False, f"проверка упала: {type(e).__name__}")
    return out


# ------------------------------------------------------------------ состояние и письма

def evaluate(state: dict, results: dict[str, tuple[bool, str]], now: float, cfg) -> list[dict]:
    """Обновить состояние проверок и вернуть письма: alert (новый сбой), remind (сбой не прошёл), recovered."""
    need, remind_s = int(cfg["MONITOR_FAILS"]), float(cfg["MONITOR_REMIND_H"]) * 3600
    checks = state.setdefault("checks", {})
    mails = []
    for name, (ok, text) in results.items():
        c = checks.setdefault(name, {"ok": True, "fails": 0, "alerted": False})
        was_cached = name == "llm" and c.get("checked_at") is not None and c.get("text") == text and c.get("ok") == ok \
            and now - c["checked_at"] < float(cfg["MONITOR_LLM_EVERY_S"])
        if not was_cached:
            c["checked_at"] = now
            c["fails"] = 0 if ok else c.get("fails", 0) + 1
        c["ok"], c["text"] = ok, text
        if ok and c.get("alerted"):
            mails.append({"kind": "recovered", "check": name, "text": text, "since": c.get("since"),
                          "last_mail": c.get("last_mail")})
            c.update(alerted=False, since=None, last_mail=None)
        elif not ok and not was_cached:
            if c.get("since") is None:  # время первого сбоя (0 — тоже время, поэтому не «or»)
                c["since"] = now
            if not c.get("alerted") and c["fails"] >= need:
                mails.append({"kind": "alert", "check": name, "text": text, "since": c["since"]})
                c.update(alerted=True, last_mail=now)
            elif c.get("alerted") and now - (c.get("last_mail") or 0) >= remind_s:
                mails.append({"kind": "remind", "check": name, "text": text, "since": c["since"]})
                c["last_mail"] = now
        if ok:
            c["since"] = None
    state["last_run"] = now
    return mails


def compose(mails: list[dict], results: dict[str, tuple[bool, str]], cfg, now: float) -> tuple[str, str]:
    host = cfg["MONITOR_BASE_URL"].split("//")[-1].rstrip("/")
    bad = [m for m in mails if m["kind"] != "recovered"]
    title = "сбой" if bad else "восстановлено"
    names = ", ".join(CHECKS[m["check"]][0] for m in (bad or mails))
    subject = f"Драфт ({host}): {title} — {names}"
    ts = lambda t: datetime.fromtimestamp(t, UTC).astimezone().strftime("%d.%m %H:%M") if t else "—"  # noqa: E731
    lines = [f"Мониторинг стенда {cfg['MONITOR_BASE_URL']}, {ts(now)}.", ""]
    for m in mails:
        what = {"alert": "СБОЙ", "remind": "сбой продолжается", "recovered": "восстановлено"}[m["kind"]]
        lines.append(f"{CHECKS[m['check']][0]}: {what}. {m['text']}" + (f" (с {ts(m['since'])})" if m.get("since") else ""))
    lines += ["", "Все проверки:"]
    lines += [f"  {'ok  ' if ok else 'СБОЙ'} {CHECKS[n][0]}: {t}" for n, (ok, t) in results.items()]
    lines += ["", "Что делать — docs/ARCHITECTURE.md, раздел 11.1 «Мониторинг стенда» (по каждой проверке).",
              "Письмо отправил spectrek-monitor.timer; журнал — journalctl -u spectrek-monitor.service."]
    return subject, "\n".join(lines)


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def signing_key(secret: str, date: str, region: str, service: str) -> bytes:
    return _sign(_sign(_sign(_sign(("AWS4" + secret).encode(), date), region), service), "aws4_request")


def sigv4_headers(method: str, url: str, body: bytes, *, key_id: str, secret: str, region: str,
                  service: str = "ses", now: datetime | None = None) -> dict[str, str]:
    """Заголовки AWS Signature V4 (Postbox принимает подпись SES)."""
    from urllib.parse import urlsplit

    u = urlsplit(url)
    t = now or datetime.now(UTC)
    amz, date = t.strftime("%Y%m%dT%H%M%SZ"), t.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body).hexdigest()
    headers = {"content-type": "application/json", "host": u.netloc, "x-amz-date": amz}
    signed = ";".join(sorted(headers))
    canonical = "\n".join([method, u.path or "/", u.query, *(f"{k}:{headers[k]}" for k in sorted(headers)), "",
                           signed, payload_hash])
    scope = f"{date}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    sig = hmac.new(signing_key(secret, date, region, service), to_sign.encode(), hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-Amz-Date": amz, "X-Amz-Content-Sha256": payload_hash,
            "Authorization": f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, SignedHeaders={signed}, Signature={sig}"}


def send_mail(cfg, subject: str, text: str, h=http) -> tuple[bool, str]:
    to = [x.strip() for x in cfg.get("MONITOR_TO", "").split(",") if x.strip()]
    key_id, secret = cfg.get("POSTBOX_ACCESS_KEY_ID"), cfg.get("POSTBOX_SECRET_ACCESS_KEY")
    if not to:
        return False, "MONITOR_TO не задан"
    if not (key_id and secret):
        return False, "нет ключей Postbox"
    endpoint = (cfg.get("POSTBOX_ENDPOINT") or "https://postbox.cloud.yandex.net").rstrip("/")
    url = endpoint + "/v2/email/outbound-emails"
    body = json.dumps({"FromEmailAddress": cfg["MONITOR_FROM"], "Destination": {"ToAddresses": to},
                       "Content": {"Simple": {"Subject": {"Data": subject, "Charset": "UTF-8"},
                                              "Body": {"Text": {"Data": text, "Charset": "UTF-8"}}}}},
                      ensure_ascii=False).encode()
    headers = sigv4_headers("POST", url, body, key_id=key_id, secret=secret,
                            region=cfg.get("POSTBOX_REGION") or "ru-central1")
    code, resp, _ = h("POST", url, body=body, headers=headers, timeout=30.0)
    if code == 200:
        return True, "отправлено"
    return False, f"Postbox ответил {code or 'нет ответа'}: {resp.decode(errors='replace')[:200]}"


# ------------------------------------------------------------------ запуск

def load_state(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(path: str, state: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Мониторинг стенда «Драфт»")
    ap.add_argument("--print", action="store_true", help="только показать итог, без писем и записи состояния")
    ap.add_argument("--test-mail", action="store_true", help="отправить пробное письмо")
    args = ap.parse_args(argv)
    cfg = config()
    now = time.time()
    if args.test_mail:
        ok, info = send_mail(cfg, "Драфт: пробное письмо мониторинга",
                             f"Мониторинг стенда {cfg['MONITOR_BASE_URL']} настроен. Письма придут при сбое и "
                             f"восстановлении.")
        print(("OK: " if ok else "ОШИБКА: ") + info)
        return 0 if ok else 1
    state = load_state(cfg["MONITOR_STATE"])
    results = run_checks(cfg, state, now)
    for n, (ok, t) in results.items():
        print(f"{'ok  ' if ok else 'FAIL'} {n}: {t}")
    if args.print:
        return 0 if all(ok for ok, _ in results.values()) else 1
    mails = evaluate(state, results, now, cfg)
    if mails:
        subject, text = compose(mails, results, cfg, now)
        if not cfg.get("MONITOR_TO", "").strip():
            # Почта ещё не задана (её даст владелец): письмо — только в журнал (journalctl -u spectrek-monitor),
            # состояние как после отправки, чтобы не повторять одно и то же каждые 5 минут.
            print(f"письмо не отправлено — MONITOR_TO пуст (письма выключены): «{subject}»")
            print(text)
        else:
            ok, info = send_mail(cfg, subject, text)
            print(f"письмо «{subject}»: {info}")
            if not ok:  # Postbox не принял (сеть, ключи) — повторим при следующем запуске
                for m in mails:
                    c = state["checks"][m["check"]]
                    if m["kind"] == "alert":
                        c["alerted"] = False
                    elif m["kind"] == "recovered":
                        c.update(alerted=True, since=m.get("since"), last_mail=m.get("last_mail"))
    save_state(cfg["MONITOR_STATE"], state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
