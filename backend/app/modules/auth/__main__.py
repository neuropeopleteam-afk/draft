"""Служебные учётные записи (администратор, аналитик ФСП) и сброс второго фактора — с сервера, без интерфейса.

    python -m app.modules.auth add-staff --email admin@company.ru --role admin
        пароль берётся из переменной STAFF_PASSWORD (или спрашивается в терминале); почта считается подтверждённой.
        Второй фактор для admin и fsp_analyst обязателен: при первом входе платформа попросит подключить приложение.
    python -m app.modules.auth reset-2fa --email user@example.com
        снять второй фактор (телефон потерян), все сеансы пользователя отзываются.
    python -m app.modules.auth list-2fa
        у кого подключён или начат второй фактор.

Регистрация через API для этих ролей закрыта (RegisterIn допускает только candidate и employer).
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from sqlalchemy import select

from app.core.db import SessionLocal, get_engine, utcnow
from app.core.enums import ConsentKind, UserRole
from app.core.legal import CONSENT_VERSION
from app.core.security import hash_password
from app.modules.auth import twofa
from app.modules.auth.models import Consent, User


def add_staff(email: str, role: str, password: str | None) -> int:
    role_e = UserRole(role)
    if role_e not in twofa.staff_roles():
        print(f"Роль {role} не служебная: допустимы {', '.join(r.value for r in twofa.staff_roles())}", file=sys.stderr)
        return 2
    pwd = password or os.environ.get("STAFF_PASSWORD") or getpass.getpass("Пароль (не короче 12 символов): ")
    if len(pwd) < 12 or not (any(c.isalpha() for c in pwd) and any(c.isdigit() for c in pwd)):
        print("Пароль служебной учётки: не короче 12 символов, буквы и цифры", file=sys.stderr)
        return 2
    email = email.strip().lower()
    try:  # та же проверка, что у формы входа (pydantic EmailStr): иначе учётка не сможет войти
        from pydantic import TypeAdapter, EmailStr
        email = TypeAdapter(EmailStr).validate_python(email)
    except Exception as e:
        reason = next((ln.strip() for ln in str(e).splitlines() if "valid" in ln), str(e))
        print(f"Почта не годится для входа: {reason}", file=sys.stderr)
        return 2
    get_engine()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)):
            print(f"Учётная запись {email} уже существует", file=sys.stderr)
            return 1
        u = User(email=email, password_hash=hash_password(pwd), role=role_e, is_email_verified=True,
                 email_verified_at=utcnow(), is_demo=False)
        db.add(u)
        db.flush()
        db.add(Consent(user_id=u.id, kind=ConsentKind.processing, document_version=CONSENT_VERSION))
        db.commit()
    print(f"Создана учётная запись {email} ({role}). Второй фактор {'обязателен: подключение при первом входе' if role in twofa.get_settings().twofa_required_role_set else 'по желанию'}.")
    return 0


def reset_2fa(email: str) -> int:
    get_engine()
    with SessionLocal() as db:
        target = db.scalar(select(User).where(User.email == email.strip().lower()))
        if target is None:
            print("Пользователь не найден", file=sys.stderr)
            return 1
        tf = twofa.get(db, target)
        if tf is None:
            print("Второй фактор не подключён", file=sys.stderr)
            return 1
        twofa._drop(db, tf)
        target.token_version += 1
        db.commit()
    print(f"Второй фактор снят у {email}, сеансы отозваны")
    return 0


def list_2fa() -> int:
    get_engine()
    with SessionLocal() as db:
        rows = twofa.admin_list(db)
    if not rows:
        print("Второй фактор ни у кого не подключён")
    for r in rows:
        print(f"{r['email']:<48} {r['role'].value:<12} {'включён' if r['enabled'] else 'не завершён':<12} "
              f"резервных {r['recovery_codes_left']}{' демо' if r['is_demo'] else ''}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.modules.auth", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add-staff", help="создать учётную запись администратора или аналитика ФСП")
    a.add_argument("--email", required=True)
    a.add_argument("--role", required=True, choices=[r.value for r in twofa.staff_roles()])
    a.add_argument("--password", help="лучше через STAFF_PASSWORD или ввод в терминале")
    r = sub.add_parser("reset-2fa", help="снять второй фактор пользователю")
    r.add_argument("--email", required=True)
    sub.add_parser("list-2fa", help="у кого подключён второй фактор")
    ns = ap.parse_args(argv)
    if ns.cmd == "add-staff":
        return add_staff(ns.email, ns.role, ns.password)
    if ns.cmd == "reset-2fa":
        return reset_2fa(ns.email)
    return list_2fa()


if __name__ == "__main__":
    sys.exit(main())
