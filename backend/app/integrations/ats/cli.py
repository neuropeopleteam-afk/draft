"""Импорт токенов ATS из файла секретов в компанию и проверка подключения — без вывода токенов.

    python -m app.integrations.ats.cli import-env --employer-email hr@company.ru [--force]
    python -m app.integrations.ats.cli status --employer-email hr@company.ru
    python -m app.integrations.ats.cli check --employer-email hr@company.ru [--provider talantix]

Переменные (secrets/ats.env, подключается docker-compose как ATS_ENV_FILE):
* ``TALANTIX_TOKENS_JSON`` — JSON со ссылки из личного кабинета Talantix, или ``TALANTIX_ACCESS_TOKEN`` +
  ``TALANTIX_REFRESH_TOKEN``; ``TALANTIX_VACANCY_ID`` — вакансия по умолчанию;
* ``POTOK_TOKEN``, ``POTOK_VACANCY_ID``;
* ``HUNTFLOW_TOKEN``, ``HUNTFLOW_ACCOUNT_ID``, ``HUNTFLOW_VACANCY_ID``, ``HUNTFLOW_BASE_URL`` (необязательно).

Refresh-токен Talantix одноразовый: после первого обновления пара из файла устаревает, актуальная живёт в БД
(зашифрованной). Поэтому повторный импорт Talantix без ``--force`` пропускается, если токены уже есть.
"""
from __future__ import annotations

import argparse
import uuid
import sys

from sqlalchemy import select

from app.core.db import SessionLocal, get_engine
from app.integrations.ats import providers
from app.integrations.ats import service as svc
from app.integrations.ats.clients import AtsError
from app.integrations.ats.demo import reset_links
from app.integrations.ats.providers.talantix import parse_tokens
from app.integrations.crypto import encrypt, mask
from app.integrations.settings import get_isettings


def _company_id(db, args):
    from app.modules.auth.models import User
    from app.modules.profiles.models import Company, EmployerProfile

    if args.company_id:
        return uuid.UUID(args.company_id)
    if args.employer_email:
        cid = db.scalar(select(EmployerProfile.company_id).join(User, User.id == EmployerProfile.user_id)
                        .where(User.email == args.employer_email.strip().lower()))
    else:
        cid = db.scalar(select(Company.id).where(Company.name == args.company_name))
    if cid is None:
        sys.exit("Компания не найдена (укажите --employer-email, --company-name или --company-id)")
    return cid


def import_env(db, company_id, force: bool = False) -> list[str]:
    s, out = get_isettings(), []
    raw = s.talantix_tokens_json or s.talantix_access_token
    if raw:
        conn = providers.connection(db, company_id, "talantix")
        has = conn.mode == "real" and providers.secrets_of(conn).get("access_token")
        if has and not force:
            out.append("Talantix: токены уже в БД (refresh одноразовый) — пропущено, --force чтобы заменить")
        else:
            t = parse_tokens(raw, s.talantix_refresh_token)
            if conn.mode != "real" or conn.base_url:
                reset_links(db, company_id, "talantix")
            conn.mode, conn.base_url, conn.enabled = "real", None, True
            providers.set_secrets(conn, {"access_token": t["access_token"], "refresh_token": t["refresh_token"]})
            conn.token_expires_at, conn.refresh_expires_at = t["expires_at"], t["refresh_expires_at"]
            conn.source_id = None
            if s.talantix_vacancy_id:
                conn.vacancy_id, conn.vacancy_title = s.talantix_vacancy_id, None
            out.append(f"Talantix: access {mask(t['access_token'])}, refresh {'есть' if t['refresh_token'] else 'нет'}")
    if s.potok_token:
        conn = providers.connection(db, company_id, "potok")
        if conn.mode != "real" or conn.base_url:
            reset_links(db, company_id, "potok")
        conn.mode, conn.base_url, conn.enabled = "real", None, True
        providers.set_secrets(conn, {"token": s.potok_token.strip()})
        if s.potok_vacancy_id:
            conn.vacancy_id, conn.vacancy_title = s.potok_vacancy_id, None
        out.append(f"Поток: токен {mask(s.potok_token)}")
    if s.huntflow_token:
        st = svc.company_settings(db, company_id)
        if (st.huntflow_base_url or "") != (s.huntflow_base_url or ""):
            reset_links(db, company_id, "huntflow")
        st.huntflow_token_enc = encrypt(s.huntflow_token.strip())
        st.huntflow_base_url = (s.huntflow_base_url or "").rstrip("/") or None
        st.huntflow_account_id = s.huntflow_account_id or st.huntflow_account_id
        st.huntflow_vacancy_id = s.huntflow_vacancy_id or st.huntflow_vacancy_id
        st.huntflow_enabled = bool(st.huntflow_account_id)
        out.append(f"Хантфлоу: токен {mask(s.huntflow_token)}, account_id {st.huntflow_account_id or 'не задан'}")
    db.commit()
    return out or ["В окружении нет токенов ATS (TALANTIX_*, POTOK_TOKEN, HUNTFLOW_TOKEN)"]


def status(db, company_id) -> list[str]:
    from app.integrations.ats.router import provider_out

    rows = []
    for code in providers.PROVIDERS:
        p = provider_out(db, company_id, code)
        rows.append(f"{p['title']}: {'включено' if p['enabled'] else 'выключено'}, режим {p['mode']}, "
                    f"токен {p['token_masked'] or 'нет'}, вакансия {p['vacancy_id'] or '—'}, "
                    f"связано кандидатов {p['candidates_linked']}")
    return rows


def check(db, company_id, only: str | None) -> list[str]:
    rows = []
    for code in [only] if only else providers.PROVIDERS:
        try:
            res = providers.make(db, company_id, code).check()
            rows.append(f"{providers.TITLES[code]}: OK — " + "; ".join(res.get("details") or []))
        except AtsError as e:
            rows.append(f"{providers.TITLES[code]}: ошибка — {e}")
    db.commit()
    return rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m app.integrations.ats.cli")
    ap.add_argument("command", choices=["import-env", "status", "check"])
    ap.add_argument("--employer-email")
    ap.add_argument("--company-name")
    ap.add_argument("--company-id")
    ap.add_argument("--provider", choices=list(providers.PROVIDERS))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    get_engine()  # вне приложения движок БД сам не создаётся: без этого SessionLocal() — UnboundExecutionError
    with SessionLocal() as db:
        cid = _company_id(db, args)
        if args.command == "import-env":
            rows = import_env(db, cid, args.force)
        elif args.command == "status":
            rows = status(db, cid)
        else:
            rows = check(db, cid, args.provider)
    print("\n".join(rows))


if __name__ == "__main__":
    main()
