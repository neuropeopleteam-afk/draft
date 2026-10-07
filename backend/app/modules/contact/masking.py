"""Маскирование контактов в переписке до принятия приглашения.

До принятия кандидат обезличен: в тексте сообщений обеих сторон скрываются телефоны, почты, ссылки (в том числе
на мессенджеры), ники Telegram и «обходные» записи вроде «тг: ivan_dev», «ivan собака mail точка ru», номер
цифрами прописью. Маскирование выполняется при сохранении: исходный текст с контактом на сервере не хранится и
позже не раскрывается. Суммы зарплат («250 000–300 000», «250000-300000») телефоном не считаются.
"""
from __future__ import annotations

import re

MASK = "[контакт скрыт до принятия приглашения]"

_EMAIL = re.compile(
    r"[\w.+\-]+\s*(?:@|\(at\)|\[at\]|\s(?:собака|at)\s)\s*[\w\-]+"
    r"(?:\s*(?:\.|\sточка\s|\sdot\s|\(dot\)|\[dot\])\s*[\w\-]+)+", re.IGNORECASE)
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
# Домены без схемы: t.me/…, wa.me/…, vk.com/…, hh.ru/…, github.com/…; без .net и .io — «ASP.NET», «socket.io»
_DOMAIN = re.compile(r"(?<![\w@])[\w\-]+(?:\.[\w\-]+)*\.(?:ru|рф|com|me|org|su|pro|ly|link|cc|online|site)\b(?:/\S*)?",
                     re.IGNORECASE)
_HANDLE = re.compile(r"(?<![\w.])@[A-Za-z][\w]{3,31}\b")
# Мессенджер + ник латиницей или номер: «тг ivan_dev», «telegram: ivan», «вотсап 8912…», «skype ivan.petrov»
_MESSENGER = re.compile(
    r"\b(?:telegram|телеграмм?|телега|тг|tg|whats\s?app|ватсап|вотсап|viber|вайбер|skype|скайп|discord|дискорд|icq)"
    r"\b\s*[:\-—=]?\s*[@+]?[A-Za-z0-9_][A-Za-z0-9_.\-]{2,}", re.IGNORECASE)
# Кандидаты в телефоны: цифры с разделителями; решение — по числу цифр и началу номера (_is_phone)
_DIGITS = re.compile(r"(?<![\w])\+?\s*\d(?:[\s\-.()]{0,3}\d){6,14}(?![\w])")
_DIGIT_WORDS = r"(?:ноль|один|одна|два|две|три|четыре|пять|шесть|семь|восемь|девять)"
_PHONE_WORDS = re.compile(rf"\b{_DIGIT_WORDS}(?:[\s,\-]+{_DIGIT_WORDS}){{6,}}\b", re.IGNORECASE)
_CITY = re.compile(r"^\d{3}[\s\-.]\d{2}[\s\-.]\d{2}$")


def _is_phone(s: str) -> bool:
    d = re.sub(r"\D", "", s)
    if s.lstrip().startswith("+"):
        return 10 <= len(d) <= 15
    if len(d) == 11 and d[0] in "78":
        return True
    if len(d) == 10 and d[0] == "9":
        return True
    return len(d) == 7 and bool(_CITY.match(s.strip()))


def _phones(text: str) -> tuple[str, int]:
    n = 0

    def repl(m: re.Match) -> str:
        nonlocal n
        if _is_phone(m.group(0)):
            n += 1
            return MASK
        return m.group(0)

    return _DIGITS.sub(repl, text), n


def mask_contacts(text: str) -> tuple[str, int]:
    """(текст с замаскированными контактами, число замен)."""
    total = 0
    out = text
    for rx in (_EMAIL, _URL, _MESSENGER, _DOMAIN, _HANDLE, _PHONE_WORDS):
        out, n = rx.subn(MASK, out)
        total += n
    out, n = _phones(out)
    total += n
    if total:  # соседние маски подряд — одной
        out = re.sub(rf"{re.escape(MASK)}(?:[\s,;]*{re.escape(MASK)})+", MASK, out).strip()
    return out, total
