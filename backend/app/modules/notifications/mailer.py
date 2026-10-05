"""Модуль notifications: адаптер отправки почты.

* DevMailer — пишет письмо (и код) в лог; используется, пока не настроен Postbox.
* PostboxMailer — Yandex Cloud Postbox по HTTPS API (SESv2-совместимый) через boto3.
  SMTP-порты на сервере закрыты, поэтому только HTTPS.
"""
from dataclasses import dataclass
import logging
from typing import Protocol

from app.core.config import Settings, get_settings

log = logging.getLogger("notifications")


@dataclass
class Message:
    to: str
    subject: str
    text: str
    html: str | None = None


class Mailer(Protocol):
    name: str

    def send(self, msg: Message) -> None: ...


class DevMailer:
    name = "dev"

    def send(self, msg: Message) -> None:
        log.warning("DEV-MAIL to=%s subject=%r\n%s", msg.to, msg.subject, msg.text)


class PostboxMailer:
    name = "postbox"

    def __init__(self, s: Settings):
        import boto3  # импорт по требованию: в тестах и dev-режиме не нужен

        self._from = s.mail_from
        self._client = boto3.client(
            "sesv2",
            endpoint_url=s.postbox_endpoint,
            region_name=s.postbox_region,
            aws_access_key_id=s.postbox_access_key_id,
            aws_secret_access_key=s.postbox_secret_access_key,
        )

    def send(self, msg: Message) -> None:
        body = {"Text": {"Data": msg.text, "Charset": "UTF-8"}}
        if msg.html:
            body["Html"] = {"Data": msg.html, "Charset": "UTF-8"}
        self._client.send_email(
            FromEmailAddress=self._from,
            Destination={"ToAddresses": [msg.to]},
            Content={"Simple": {"Subject": {"Data": msg.subject, "Charset": "UTF-8"}, "Body": body}},
        )
        log.info("Postbox: письмо отправлено to=%s subject=%r", msg.to, msg.subject)


_mailer: Mailer | None = None


def get_mailer() -> Mailer:
    global _mailer
    if _mailer is None:
        s = get_settings()
        _mailer = PostboxMailer(s) if s.effective_mail_backend == "postbox" else DevMailer()
    return _mailer


def send_verification_code(email: str, code: str) -> None:
    s = get_settings()
    text = (
        f"Здравствуйте!\n\nКод подтверждения почты: {code}\n"
        f"Код действует {s.email_code_ttl_minutes} минут.\n\n"
        "Если вы не регистрировались на платформе спецтрека ФСП, просто проигнорируйте письмо."
    )
    html = (
        f"<p>Здравствуйте!</p><p>Код подтверждения почты: <b style='font-size:20px'>{code}</b></p>"
        f"<p>Код действует {s.email_code_ttl_minutes} минут.</p>"
    )
    msg = Message(to=email, subject="Код подтверждения почты", text=text, html=html)
    try:
        get_mailer().send(msg)
    except Exception:  # почта не должна ронять регистрацию; код можно запросить повторно
        log.exception("Не удалось отправить письмо на %s", email)
    if s.effective_dev_mode:
        log.warning("DEV_MODE: код подтверждения для %s: %s", email, code)
