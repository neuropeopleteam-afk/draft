#!/usr/bin/env python3
"""Ретранслятор «Драфта» для зарубежных API (OpenRouter, ElevenLabs, Deepgram, Anam). Написан 10.10.2026, замена
/opt/fsp_relay/relay.py на сервере «Мадрид» (см. infra/relay/README.md). Только стандартная библиотека.

Правила:
- HTTPS на RELAY_PORT (18743) с сертификатом и ключом из каталога учётных данных systemd (LoadCredential cert/key/token);
- клиент: IP из RELAY_ALLOWED_IPS и заголовок X-Relay-Token, равный содержимому файла token; иначе 403 без подробностей;
- маршрут: заголовок X-Relay-Host из белого списка RELAY_HOSTS → https://<host><path>; без заголовка — прежнее поведение:
  путь должен начинаться с /api/v1/ и уходит на openrouter.ai (совместимость с LLM-клиентом backend);
- тело запроса до RELAY_MAX_BODY байт (по умолчанию 8 МБ — записи речи), пересылается как есть, в том числе бинарное;
- пересылаются только заголовки из списка FORWARD_HEADERS (ключи поставщиков идут от клиента, у ретранслятора их нет);
- ответ отдаётся потоком кусками по 64 КБ с принудительной отправкой (SSE/стриминг проходят без задержки);
- в журнал — метод, хост, путь без строки запроса, статус и длительность; тела и заголовки не журналируются.
"""
from __future__ import annotations

import http.client
import logging
import os
import ssl
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

PORT = int(os.environ.get("RELAY_PORT", "18743"))
ALLOWED_IPS = {ip.strip() for ip in os.environ.get("RELAY_ALLOWED_IPS", "91.210.106.252").split(",") if ip.strip()}
HOSTS = {h.strip().lower() for h in os.environ.get(
    "RELAY_HOSTS", "openrouter.ai,api.elevenlabs.io,api.deepgram.com,api.anam.ai").split(",") if h.strip()}
LEGACY_HOST = os.environ.get("RELAY_LEGACY_HOST", "openrouter.ai")
LEGACY_PREFIX = os.environ.get("RELAY_LEGACY_PREFIX", "/api/v1/")
MAX_BODY = int(os.environ.get("RELAY_MAX_BODY", str(8 * 1024 * 1024)))
UPSTREAM_TIMEOUT = float(os.environ.get("RELAY_UPSTREAM_TIMEOUT", "150"))
FORWARD_HEADERS = ("authorization", "content-type", "accept", "xi-api-key", "x-title", "http-referer", "x-request-id")
CRED_DIR = os.environ.get("CREDENTIALS_DIRECTORY", "/run/credentials/fsp-relay.service")

log = logging.getLogger("relay")


def _read_cred(name: str) -> str:
    with open(os.path.join(CRED_DIR, name), encoding="utf-8") as f:
        return f.read().strip()


TOKEN = _read_cred("token")


class Handler(BaseHTTPRequestHandler):
    server_version = "draft-relay/2"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # стандартный журнал печатает строку запроса целиком — не нужно
        return

    def _deny(self, code: int = 403) -> None:
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _target(self) -> tuple[str, str] | None:
        """(host, path) или None, если маршрут не разрешён."""
        path = self.path if self.path.startswith("/") else "/" + self.path
        if "://" in path or path.startswith("//"):
            return None
        host = (self.headers.get("X-Relay-Host") or "").strip().lower()
        if host:
            return (host, path) if host in HOSTS else None
        return (LEGACY_HOST, path) if path.startswith(LEGACY_PREFIX) else None

    def _handle(self) -> None:
        started = time.monotonic()
        if self.client_address[0] not in ALLOWED_IPS or self.headers.get("X-Relay-Token", "") != TOKEN:
            return self._deny(403)
        target = self._target()
        if not target:
            return self._deny(404)
        host, path = target
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._deny(413)
        body = self.rfile.read(length) if length else b""
        fwd = {k: v for k, v in ((h, self.headers.get(h)) for h in FORWARD_HEADERS) if v}
        fwd["Host"] = host
        if body:
            fwd["Content-Length"] = str(len(body))
        status = 502
        try:
            conn = http.client.HTTPSConnection(host, 443, timeout=UPSTREAM_TIMEOUT, context=ssl.create_default_context())
            conn.request(self.command, path, body=body or None, headers=fwd)
            resp = conn.getresponse()
            status = resp.status
            self.send_response(status)
            ctype = resp.getheader("Content-Type")
            if ctype:
                self.send_header("Content-Type", ctype)
            clen = resp.getheader("Content-Length")
            if clen and not resp.getheader("Transfer-Encoding"):
                self.send_header("Content-Length", clen)
                self.end_headers()
                while chunk := resp.read(65536):
                    self.wfile.write(chunk)
            else:
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                while chunk := resp.read(65536):
                    self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            conn.close()
        except Exception as e:  # поставщик недоступен/тайм-аут — 502 без текста ошибки наружу
            log.warning("%s %s%s -> %s", self.command, host, urlsplit(path).path, type(e).__name__)
            try:
                self._deny(502)
            except Exception:
                pass
            return
        finally:
            log.info("%s %s%s %s %dms", self.command, host, urlsplit(path).path, status, (time.monotonic() - started) * 1000)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _handle


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(os.path.join(CRED_DIR, "cert"), os.path.join(CRED_DIR, "key"))
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    srv.daemon_threads = True
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    log.info("relay: порт %s, хосты %s, клиенты %s, тело до %d байт", PORT, ",".join(sorted(HOSTS)), ",".join(sorted(ALLOWED_IPS)), MAX_BODY)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
