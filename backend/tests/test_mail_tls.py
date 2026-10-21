"""Чек-лист экспертов 20.10, п. 10а: отправка почты проверяет TLS-сертификат сервера.

Почта уходит через PostboxMailer (HTTPS API, boto3). Проверяем по-настоящему, а не по настройке: поднимаем на 127.0.0.1
HTTPS-сервер с самоподписанным сертификатом и отправляем письмо на него.
* без доверия к этому сертификату отправка падает на проверке TLS (botocore SSLError), запрос до сервера не доходит;
* контроль: тот же сервер, сертификат добавлен в доверенные (AWS_CA_BUNDLE) — запрос доходит, значит падение выше
  вызвано именно проверкой сертификата, а не чем-то другим;
* адрес Postbox по умолчанию — https, проверка сертификата у клиента включена.
"""
from __future__ import annotations

import datetime as dt
import http.server
import ipaddress
import ssl
import threading

import pytest

pytest.importorskip("boto3")
crypto = pytest.importorskip("cryptography")

from botocore.exceptions import SSLError  # noqa: E402
from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.modules.notifications import mailer as M  # noqa: E402


def _self_signed(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    crt, pem = tmp_path / "srv.crt", tmp_path / "srv.key"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    return crt, pem


@pytest.fixture
def tls_server(tmp_path):
    crt, pem = _self_signed(tmp_path)
    hits: list[str] = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            hits.append(self.path)
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            body = b'{"MessageId":"tls-test"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):  # тихо
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, pem)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"https://127.0.0.1:{srv.server_address[1]}", crt, hits
    srv.shutdown()
    srv.server_close()


def _mailer(endpoint: str) -> M.PostboxMailer:
    s = Settings(mail_backend="postbox", postbox_endpoint=endpoint, postbox_access_key_id="AKIDTEST",
                 postbox_secret_access_key="test-secret", mail_from="noreply@example.org")
    return M.PostboxMailer(s)


MSG = M.Message(to="user@example.org", subject="Проверка TLS", text="текст")


def test_untrusted_certificate_rejected(tls_server, monkeypatch):
    url, _crt, hits = tls_server
    monkeypatch.delenv("AWS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    with pytest.raises(SSLError):
        _mailer(url).send(MSG)
    assert hits == [], "запрос не должен дойти до сервера с недоверенным сертификатом"


def test_trusted_certificate_control(tls_server, monkeypatch):
    url, crt, hits = tls_server
    monkeypatch.setenv("AWS_CA_BUNDLE", str(crt))
    _mailer(url).send(MSG)  # не падает: тот же сервер, сертификат доверенный
    assert len(hits) == 1


def test_default_endpoint_is_https_and_verify_on():
    s = Settings()
    assert s.postbox_endpoint.startswith("https://")
    m = _mailer(s.postbox_endpoint)
    assert m._client.meta.endpoint_url.startswith("https://")
    assert m._client._endpoint.http_session._verify not in (False, None)
