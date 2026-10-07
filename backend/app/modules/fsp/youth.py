"""Возраст — только условия контакта, никогда не фактор подбора."""
from app.core.errors import api_error

AGE_GROUPS = ("18+", "16-17", "14-15")
WARNING = ("Для кандидата 16–17 лет: сокращённое рабочее время, стажировка или лёгкий труд. "
           "Перед оформлением работодатель проверяет документы и допустимость условий. "
           "Отметка о согласии представителя заявлена кандидатом, не проверена платформой.")


def employment_safety(profile) -> dict:
    minor = getattr(profile, "age_group", "18+") != "18+"
    return {"minor": minor, "age_group": profile.age_group if minor else None,
            "parental_consent": bool(profile.parental_consent) if minor else None,
            "offer_allowed": not minor or (profile.age_group == "16-17" and profile.parental_consent),
            "allowed_formats": ["internship", "light_work"] if minor else ["employment", "internship", "light_work"],
            "warning": WARNING if minor else None}


def check_offer(profile, terms: dict) -> None:
    if getattr(profile, "age_group", "18+") == "18+":
        return
    if profile.age_group == "14-15":
        raise api_error(422, "youth_offer_not_supported",
                        "Для 14–15 лет офферы пока недоступны: нужна отдельная проверка условий работодателем")
    if not profile.parental_consent:
        raise api_error(422, "parental_consent_required", "Кандидат ещё не отметил согласие родителя или законного представителя")
    if terms.get("format") not in ("internship", "light_work") or not terms.get("reduced_time"):
        raise api_error(422, "youth_offer_restricted", "Для 16–17 лет укажите стажировку или лёгкий труд и сокращённое время")
    if not terms.get("employer_acknowledged"):
        raise api_error(422, "youth_offer_ack_required", "Подтвердите проверку ограничений для несовершеннолетнего кандидата")
