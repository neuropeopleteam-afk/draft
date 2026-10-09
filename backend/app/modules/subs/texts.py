"""Тексты уведомлений и писем. По-русски, без восклицательных знаков и эмодзи; числа — с запятой и неразрывными пробелами."""
from __future__ import annotations

from datetime import datetime

NB = "\u00a0"


def plural(n: int, forms: tuple[str, str, str]) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def rub(v: int | None) -> str:
    return "—" if v is None else f"{int(v):,}".replace(",", NB) + f"{NB}₽"


def pct(score: float | None) -> str:
    return "—" if score is None else f"{round(float(score) * 100)}{NB}%"


def day_month(dt: datetime, offset_h: int = 3) -> str:
    from datetime import timedelta

    local = dt + timedelta(hours=offset_h)
    return f"{local:%d.%m.%Y}"


def days_text(n: int) -> str:
    return f"{n}{NB}{plural(n, ('день', 'дня', 'дней'))}"


# ------------------------------------------------------------------ подписка на потребность
def match_line(row: dict) -> str:
    """Строка о кандидате: только обезличенное (ссылка К-…, категория, соответствие)."""
    card = row.get("card") or {}
    cat = (card.get("category") or {}).get("title") or row.get("category_id") or "категория не подтверждена"
    return f"{row['ref']} · {cat} · соответствие {pct(row.get('score'))} · {row.get('rank')}-е место"


def match_title(n: int) -> str:
    return f"Новых подходящих кандидатов: {n}"


def match_push(need_title: str, n: int) -> tuple[str, str]:
    return ("Новые подходящие кандидаты",
            f"«{need_title}»: в топ-10 вошли новых кандидатов — {n}. Откройте подборку.")


def match_body(need_title: str, rows: list[dict], top_n: int) -> str:
    head = f"По потребности «{need_title}» в топ-{top_n} вошли новые кандидаты после подтверждённого результата."
    return "\n".join([head, *[match_line(r) for r in rows]])


# ------------------------------------------------------------------ напоминания Н6
def inv_unanswered(company: str, position: str, salary_from: int, salary_to: int, days: int, until: datetime | None) -> tuple[str, str]:
    body = (f"Приглашение от компании «{company}» на позицию «{position}» без ответа {days_text(days)}. "
            f"Вилка: {rub(salary_from)} – {rub(salary_to)}.")
    if until is not None:
        body += f" Ответить можно до {day_month(until)}."
    return "Приглашение ждёт вашего ответа", body


def inv_expiring(company: str, position: str, until: datetime) -> tuple[str, str]:
    return ("Срок ответа на приглашение истекает завтра",
            f"Приглашение от компании «{company}» на позицию «{position}» действует до {day_month(until)}. "
            "После этого срока ответить на него будет нельзя.")


def inv_expired_employer(ref: str, position: str) -> tuple[str, str]:
    return ("Приглашение истекло без ответа",
            f"Кандидат {ref} не ответил на приглашение «{position}», срок ответа истёк. "
            "Новое приглашение этому кандидату можно отправить из карточки.")


def app_stale_employer(ref: str, vacancy: str, days: int) -> tuple[str, str]:
    return ("Отклик ждёт вашего ответа",
            f"На отклик кандидата {ref} на вакансию «{vacancy}» нет ответа {days_text(days)}. "
            "Откройте отклик и примите решение: кандидат видит статус.")


# ------------------------------------------------------------------ дайджест
def digest_subject(kind: str) -> str:
    return "Дайджест за неделю: подходящие кандидаты и напоминания" if kind == "weekly" else \
        "Дайджест: подходящие кандидаты и напоминания"


def digest_footer() -> str:
    return "Отключить письма или изменить частоту можно в кабинете: раздел «Уведомления»."
