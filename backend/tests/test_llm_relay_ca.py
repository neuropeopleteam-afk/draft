"""Ретранслятор с собственным сертификатом: при LLM_RELAY_CA_FILE клиент проверяет TLS по нему, без него — как обычно."""
import ssl

from app.core.config import get_settings
from app.modules.llm import client


def test_verify_uses_relay_ca(tmp_path, monkeypatch):
    import certifi
    ca = tmp_path / "relay.pem"
    ca.write_text(open(certifi.where()).read())  # любой валидный PEM
    monkeypatch.setenv("LLM_RELAY_URL", "https://relay.example/api/v1")
    monkeypatch.setenv("LLM_RELAY_CA_FILE", str(ca))
    get_settings.cache_clear()
    try:
        s = get_settings()
        v = client._verify("openrouter", s)
        assert isinstance(v, ssl.SSLContext)
        assert client._verify("yandex", s) is True
    finally:
        get_settings.cache_clear()


def test_verify_default_without_ca(monkeypatch):
    monkeypatch.delenv("LLM_RELAY_CA_FILE", raising=False)
    get_settings.cache_clear()
    try:
        assert client._verify("openrouter", get_settings()) is True
    finally:
        get_settings.cache_clear()


def test_verify_uses_relay_ca_b64(tmp_path, monkeypatch):
    import base64, subprocess
    key, crt = tmp_path / "k.pem", tmp_path / "c.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
                    "-keyout", str(key), "-out", str(crt), "-days", "1", "-subj", "/CN=127.0.0.1",
                    "-addext", "subjectAltName=IP:127.0.0.1"], check=True, capture_output=True)
    monkeypatch.setenv("LLM_RELAY_URL", "https://127.0.0.1:18743/api/v1")
    monkeypatch.delenv("LLM_RELAY_CA_FILE", raising=False)
    monkeypatch.setenv("LLM_RELAY_CA_PEM_B64", base64.b64encode(crt.read_bytes()).decode())
    get_settings.cache_clear()
    try:
        v = client._verify("openrouter", get_settings())
        assert isinstance(v, ssl.SSLContext) and v.cert_store_stats()["x509_ca"] == 1
    finally:
        get_settings.cache_clear()
