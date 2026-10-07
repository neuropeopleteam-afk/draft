"""Мониторинг стенда (infra/monitor/monitor.py, И10 п. 3): подпись Postbox, проверки, состояние и письма."""
from __future__ import annotations

from collections import namedtuple
from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("spectrek_monitor", ROOT / "infra" / "monitor" / "monitor.py")
mon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mon)

CFG = mon.config({"MONITOR_ENV_FILES": "", "MONITOR_TO": "owner@example.com", "POSTBOX_ACCESS_KEY_ID": "AKID",
                  "POSTBOX_SECRET_ACCESS_KEY": "secret", "MAIL_FROM": "noreply@neuropeople.pro"})


def test_sigv4_signing_key_aws_vector_and_botocore():
    # пример из документации AWS (Deriving the signing key)
    key = mon.signing_key("wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "20120215", "us-east-1", "iam")
    assert key.hex() == "f4780e2d9f65fa895f9c67b32ce1baf0b0d8a43505a000a1a9e090d414db404d"
    # та же подпись, что у botocore (им пользуется приложение через boto3) для запроса SendEmail в Postbox
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials

    url, body = "https://postbox.cloud.yandex.net/v2/email/outbound-emails", b'{"a": 1}'
    now = datetime(2026, 10, 7, 10, 0, 0, tzinfo=UTC)
    mine = mon.sigv4_headers("POST", url, body, key_id="AKID", secret="secret", region="ru-central1", now=now)
    req = AWSRequest(method="POST", url=url, data=body,
                     headers={"Content-Type": "application/json", "X-Amz-Date": "20261007T100000Z"})
    req.context["timestamp"] = "20261007T100000Z"
    auth = SigV4Auth(Credentials("AKID", "secret"), "ses", "ru-central1")
    canonical = auth.canonical_request(req)
    sig = auth.signature(auth.string_to_sign(req, canonical), req)
    assert mine["Authorization"].endswith(f"Signature={sig}"), (canonical, mine)
    assert "SignedHeaders=content-type;host;x-amz-date" in mine["Authorization"]


def test_send_mail_payload_and_errors():
    calls = []

    def h(method, url, *, body=None, headers=None, timeout=15.0):
        calls.append((method, url, json.loads(body), headers))
        return 200, b'{"MessageId": "1"}', 0.1

    ok, info = mon.send_mail(CFG, "Тема", "Текст", h=h)
    assert ok and calls[0][1] == "https://postbox.cloud.yandex.net/v2/email/outbound-emails"
    p = calls[0][2]
    assert p["Destination"]["ToAddresses"] == ["owner@example.com"] and p["FromEmailAddress"] == "noreply@neuropeople.pro"
    assert p["Content"]["Simple"]["Subject"]["Data"] == "Тема" and "secret" not in json.dumps(calls[0][3])
    assert mon.send_mail({**CFG, "MONITOR_TO": ""}, "т", "т", h=h) == (False, "MONITOR_TO не задан")
    bad = mon.send_mail(CFG, "т", "т", h=lambda *a, **k: (403, b"SignatureDoesNotMatch", 0.1))
    assert not bad[0] and "403" in bad[1]


def _http(routes):
    def h(method, url, *, body=None, headers=None, timeout=15.0):
        for k, v in routes.items():
            if url.endswith(k):
                return v
        return 0, b"timeout", 15.0
    return h


def test_checks_site_web_llm():
    assert mon.check_site(CFG, _http({"/api/health": (200, b'{"status": "ok", "db": "ok"}', 0.05)}))[0]
    ok, text = mon.check_site(CFG, _http({"/api/health": (200, b'{"status": "degraded", "db": "error"}', 0.05)}))
    assert not ok and "db=error" in text
    assert not mon.check_site(CFG, _http({}))[0]
    assert mon.check_web(CFG, _http({"/": (401, b"", 0.1)}))[0] and not mon.check_web(CFG, _http({"/": (502, b"", 1)}))[0]
    llm = {**CFG, "LLM_BASE_URL": "https://llm.api.cloud.yandex.net/v1", "LLM_API_KEY": "k", "LLM_MODEL": "yandexgpt-lite",
           "LLM_FOLDER_ID": "b1g", "LLM_PROVIDER": "yandex_ai_studio"}
    seen = []

    def h(method, url, *, body=None, headers=None, timeout=15.0):
        seen.append((url, json.loads(body), headers))
        return 403, b'{"error": "Permission denied"}', 0.3

    ok, text = mon.check_llm(llm, h)
    assert not ok and "403" in text and "прав" in text  # как 06.10
    assert seen[0][0].endswith("/chat/completions") and seen[0][1]["model"] == "gpt://b1g/yandexgpt-lite"
    assert seen[0][2]["Authorization"] == "Api-Key k" and seen[0][2]["OpenAI-Project"] == "b1g"
    assert mon.check_llm(llm, _http({"/chat/completions": (200, b"{}", 1.2)}))[0]
    assert mon.check_llm({**CFG}, _http({}))[0]  # LLM не настроен — не сбой


def test_checks_disk_docker_backup(tmp_path):
    U = namedtuple("U", "total used free")
    assert mon.check_disk(CFG, lambda p: U(100, 82, 18))[0]
    ok, text = mon.check_disk(CFG, lambda p: U(100 * 1024 ** 3, 95 * 1024 ** 3, 5 * 1024 ** 3))
    assert not ok and "95 %" in text

    def run(cmd):
        if cmd[1] == "inspect":
            return ("/spectrek_fsp-api-1|true|false|0|805306368\n/spectrek_fsp-db-1|true|false|0|335544320\n"
                    "/spectrek_fsp-web-1|false|false|3|33554432")
        return "750MiB / 768MiB"
    ok, text = mon.check_docker(CFG, run)
    assert not ok and "web-1: остановлен" in text and "api: память 98 %" in text
    ok, text = mon.check_docker(CFG, lambda cmd: "/spectrek_fsp-api-1|true|false|0|805306368\n"
                                "/spectrek_fsp-db-1|true|false|0|0\n/spectrek_fsp-web-1|true|false|0|0"
                                if cmd[1] == "inspect" else "508MiB / 768MiB")
    assert ok and "508 из 768 МБ" in text

    cfg = {**CFG, "MONITOR_BACKUP_DIR": str(tmp_path)}
    assert not mon.check_backup(cfg)[0]
    f = tmp_path / "spectrek_fsp_20261007_0340.sql.gz"
    f.write_bytes(b"x" * 4096)
    assert mon.check_backup(cfg)[0]
    assert not mon.check_backup(cfg, now=f.stat().st_mtime + 31 * 3600)[0]


def test_state_machine_alert_remind_recover_and_llm_hourly():
    st, cfg = {}, {**CFG, "MONITOR_FAILS": "2", "MONITOR_REMIND_H": "6"}
    bad, good = {"site": (False, "нет ответа")}, {"site": (True, "ok")}
    assert mon.evaluate(st, bad, 0, cfg) == []  # один сбой — не будим
    m = mon.evaluate(st, bad, 300, cfg)
    assert [x["kind"] for x in m] == ["alert"] and m[0]["since"] == 0
    assert mon.evaluate(st, bad, 600, cfg) == []
    assert [x["kind"] for x in mon.evaluate(st, bad, 300 + 6 * 3600, cfg)] == ["remind"]
    assert [x["kind"] for x in mon.evaluate(st, good, 7 * 3600, cfg)] == ["recovered"]
    assert mon.evaluate(st, good, 8 * 3600, cfg) == []
    subject, text = mon.compose([{"kind": "alert", "check": "llm", "text": "Yandex AI Studio: 403", "since": 0}],
                                {"llm": (False, "Yandex AI Studio: 403"), "disk": (True, "занято 82 %")}, cfg, 10)
    assert "сбой" in subject and "Yandex AI Studio" in subject and "СБОЙ" in text and "82 %" in text

    # LLM — не чаще раза в час: между проверками — прошлый итог, без повторного счёта сбоев
    st, calls = {}, []
    checks = {"llm": ("Yandex AI Studio", lambda c: calls.append(1) or (False, "Yandex AI Studio: 403"))}
    for t in (0, 300, 600):
        mon.evaluate(st, mon.run_checks(cfg, st, t, checks), t, cfg)
    assert len(calls) == 1 and st["checks"]["llm"]["fails"] == 1 and not st["checks"]["llm"]["alerted"]
    m = mon.evaluate(st, mon.run_checks(cfg, st, 3700, checks), 3700, cfg)
    assert len(calls) == 2 and [x["kind"] for x in m] == ["alert"]


def test_main_print_and_state_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MONITOR_ENV_FILES", "")
    monkeypatch.setenv("MONITOR_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("MONITOR_TO", "")
    monkeypatch.setattr(mon, "CHECKS", {"disk": ("Диск", lambda c: (False, "занято 95 %"))})
    assert mon.main(["--print"]) == 1 and not (tmp_path / "state.json").exists()
    for _ in range(2):
        assert mon.main([]) == 0
    out = capsys.readouterr().out
    assert "MONITOR_TO не задан" in out  # письмо не ушло — повторим при следующем запуске
    st = json.loads((tmp_path / "state.json").read_text())
    assert st["checks"]["disk"]["fails"] == 2 and st["checks"]["disk"]["alerted"] is False


@pytest.mark.parametrize("name", ["spectrek-monitor.service", "spectrek-monitor.timer", "monitor.env.example"])
def test_unit_files_present(name):
    text = (ROOT / "infra" / "monitor" / name).read_text()
    assert "Spectrek" in text or "MONITOR_TO" in text
