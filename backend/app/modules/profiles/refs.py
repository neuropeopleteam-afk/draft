"""Обезличенные идентификаторы кандидатов для работодателя: «C-7F3A2B» (латиница — безопасно для URL и имён файлов).

Ссылка случайная (не производная от id или почты), поэтому по ней нельзя восстановить личность.
"""
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # без 0/O и 1/I


def make_ref() -> str:
    return "C-" + "".join(secrets.choice(ALPHABET) for _ in range(6))


def new_public_ref(db: Session) -> str:
    from app.modules.profiles.models import CandidateProfile

    while True:
        ref = make_ref()
        if db.scalar(select(CandidateProfile.user_id).where(CandidateProfile.public_ref == ref)) is None:
            return ref
