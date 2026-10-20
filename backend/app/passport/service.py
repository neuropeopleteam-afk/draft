"""Выпуск, перевыпуск, отзыв и проверка паспорта грейда.

Жизненный цикл:
- выпуск — автоматически после присвоения категории (assessment.service.finish_session → on_test_finished), а для
  кандидатов, получивших категорию раньше (демо-данные, учётки до выпуска паспортов), — при первом обращении
  (ensure_current: кабинет кандидата, карточка у работодателя, PDF-профиль);
- перевыпуск — пересдача (новая дата теста, θ, навыки) или изменение состава (статус грейда, достижения ФСП):
  старый паспорт отзывается с причиной superseded, новый получает новый id;
- отзыв — понижение грейда (downgraded), аннулирование результата по проверке достоверности (integrity_annulled,
  только решением администратора: автоматических наказаний за сигналы античита нет), удаление учётной записи
  (account_deleted), сам кандидат (candidate_revoked — и может выпустить новую ссылку).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import logging
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import as_aware, utcnow
from app.core.errors import api_error
from app.modules.auth.models import User
from app.modules.catalog.models import Category
from app.modules.catalog.seed_data import DIRECTION_TITLES, GRADES, GRADE_ORDER as _PLATFORM_GRADE_ORDER
from app.modules.profiles.facts import DISCIPLINE_TITLES, LEVEL_TITLES, card, load_bundles, passport_status
from app.modules.profiles.models import CandidateProfile
from app.passport import crypto
from app.passport.models import GradePassport, PassportKey

log = logging.getLogger(__name__)
GRADE_ORDER = [g for g in _PLATFORM_GRADE_ORDER if g != "intern"]  # junior … senior (с флагом — и Lead, Principal)
STATUS_TITLES = {"confirmed": "подтверждён", "preliminary": "предварительно"}
REASONS = {
    "superseded": "заменён новым паспортом после пересдачи или обновления данных",
    "reviewed": "заменён новым паспортом после экспертной проверки развёрнутых ответов",
    "downgraded": "грейд понижен по результату пересдачи",
    "integrity_annulled": "результат теста аннулирован по проверке достоверности",
    "account_deleted": "учётная запись кандидата удалена",
    "candidate_revoked": "ссылку отозвал сам кандидат",
    "admin": "отозван администратором платформы",
}
STATE_TITLES = {"valid": "Действителен", "revoked": "Отозван", "expired": "Истёк",
                "invalid_signature": "Подпись не сходится"}
# поля, которые меняются при каждом выпуске и не означают изменения состава
VOLATILE = ("id", "issued_at", "valid_until", "kid", "issuer")


def _iso(dt: datetime | None) -> str | None:
    return as_aware(dt).astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z") if dt else None


def _r(v, d=3):
    return None if v is None else round(float(v), d)


def verify_url(pid: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/verify/{pid}"


def methodology_url() -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/validation"


# ------------------------------------------------------------------ состав паспорта

def _p_at_least(probs: dict | None, grade: str | None) -> float | None:
    if not probs or grade not in GRADE_ORDER:
        return None
    gi = GRADE_ORDER.index(grade)
    return _r(sum(float(v) for k, v in probs.items() if k in GRADE_ORDER and GRADE_ORDER.index(k) >= gi))


def build_content(db: Session, user_id: uuid.UUID) -> dict | None:
    """Состав паспорта (без id, дат выпуска и ключа) или None — категории нет, паспорт не положен.

    Источник — обезличенная карточка работодателя (profiles.facts.card) с настройками приватности кандидата:
    в паспорт не может попасть то, что кандидат скрыл от работодателей, и никогда — ФИО и контакты.
    """
    from app.modules.assessment.models import TestSession

    b = load_bundles(db, [user_id]).get(user_id)
    if b is None or not b.profile.current_category_id or not b.profile.public_ref:
        return None
    p = b.profile
    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    c = card(b, cats)
    t = b.test.value if b.test else {}
    # FIX7 п. 6: один источник статуса с карточкой и экраном «Категория» (profiles.facts.passport_status):
    # «Junior (предварительно)», открытые ответы ещё на проверке эксперта, Lead/Principal по тесту — «предварительный»
    status = passport_status(b)
    if getattr(p, "grade_provisional", False) or (c.get("category") or {}).get("ext_preliminary"):
        status = "preliminary"  # прежние признаки — на случай расхождения загрузки (не ослабляем)
    session_id = t.get("session_id")
    probs = None
    if session_id:
        try:
            ts = db.get(TestSession, uuid.UUID(session_id))
            probs = ((ts.result or {}).get("engine_result") or {}).get("probabilities") if ts else None
        except ValueError:
            probs = None
    integ = (c.get("test") or {}).get("integrity") or {}
    assessment = {
        "test_date": (c.get("test") or {}).get("date"),
        "engine": t.get("engine"),
        "theta": _r(t.get("theta")), "se": _r(t.get("se")),
        "p_grade_or_higher": _p_at_least(probs, p.current_grade_id),
        "answered": t.get("answered"), "correct": t.get("correct"),
        "integrity": integ.get("level") if isinstance(integ, dict) else None,
    } if b.test else None
    fsp = c.get("fsp") or {}
    t2 = []
    if not fsp.get("hidden") and b.passport is not None:
        src = b.passport.link_source.value
        for a in b.achievements:
            lvl = a.event_level.value if hasattr(a.event_level, "value") else a.event_level
            if not a.verified or lvl == "platform":  # мероприятия платформы (кубки) — T1, не реестр
                continue
            t2.append({"discipline": a.discipline, "discipline_title": DISCIPLINE_TITLES.get(a.discipline, a.discipline),
                       "event": a.event_name, "level": lvl, "level_title": LEVEL_TITLES.get(lvl, lvl),
                       "date": a.event_date.isoformat() if a.event_date else None, "place": a.place,
                       "result": a.result_title,
                       "source": {"registry": src, "ref": a.source_ref,
                                  "demo": src == "demo"}})
        t2.sort(key=lambda x: (x["date"] or "", x["event"]), reverse=True)
    skills = [{"tag": s["tag"], "title": s["title"], "score": _r(s.get("score"), 2)}
              for s in c.get("skills_confirmed") or []]
    cat = cats.get(p.current_category_id)
    return {
        "schema": crypto.SCHEMA,
        "subject": {"public_ref": p.public_ref},
        "category": {"id": p.current_category_id, "title": cat.title if cat else p.current_category_id,
                     "direction": p.current_direction_id, "direction_title": DIRECTION_TITLES.get(p.current_direction_id),
                     "grade": p.current_grade_id, "grade_title": GRADES.get(p.current_grade_id)},
        "grade_status": status,
        "assessment": assessment,
        "skills_t1": skills,
        "achievements_t2": t2,
        "methodology_url": methodology_url(),
    }


def fingerprint(content: dict) -> str:
    body = {k: v for k, v in content.items() if k not in VOLATILE}
    return hashlib.sha256(crypto.canonical(body)).hexdigest()


def _register_key(db: Session, key: crypto.SigningKey) -> None:
    row = db.get(PassportKey, key.kid)
    if row is None:
        db.add(PassportKey(kid=key.kid, public_key=key.public_b64, test_key=key.test_key, last_used_at=utcnow()))
    else:
        row.last_used_at = utcnow()


# ------------------------------------------------------------------ выпуск и отзыв

def active(db: Session, user_id: uuid.UUID) -> GradePassport | None:
    return db.scalar(select(GradePassport).where(GradePassport.user_id == user_id, GradePassport.revoked_at.is_(None))
                     .order_by(GradePassport.issued_at.desc()).limit(1))


def _revoke(p: GradePassport, reason: str, now: datetime | None = None) -> None:
    if p.revoked_at is None:
        p.revoked_at = now or utcnow()
        p.revoke_reason = reason


def issue(db: Session, user_id: uuid.UUID, content: dict | None = None, *, test_session_id=None) -> GradePassport | None:
    content = content if content is not None else build_content(db, user_id)
    if content is None:
        return None
    key = crypto.signing_key()
    _register_key(db, key)
    now = utcnow()
    s = get_settings()
    test_date = (content.get("assessment") or {}).get("test_date")
    base = datetime.fromisoformat(test_date).replace(tzinfo=UTC) if test_date else now
    valid_until = max(base + timedelta(days=s.passport_ttl_days), now + timedelta(days=1))
    pid = secrets.token_urlsafe(12)
    issuer = {"name": s.product_name, "url": s.public_base_url.rstrip("/"),
              "jwks_url": f"{s.public_base_url.rstrip('/')}/api/passport/keys"}
    if key.test_key:
        issuer["test_key"] = True
    claims = {**content, "id": pid, "issuer": issuer, "kid": key.kid,
              "issued_at": _iso(now), "valid_until": _iso(valid_until)}
    document, sig = crypto.sign(claims, key)
    row = GradePassport(id=pid, user_id=user_id, public_ref=content["subject"]["public_ref"],
                        category_id=content["category"]["id"], grade_status=content["grade_status"], kid=key.kid,
                        document=document, signature=sig, fingerprint=fingerprint(content),
                        test_session_id=test_session_id, issued_at=now, valid_until=valid_until)
    db.add(row)
    db.flush()
    return row


def ensure_current(db: Session, user_id: uuid.UUID, *, reason: str = "superseded",
                   test_session_id=None, content: dict | None = None) -> GradePassport | None:
    """Действующий паспорт с актуальным составом: выпускает, если нет; перевыпускает, если состав изменился.

    Кандидат, отозвавший ссылку сам, новую получает только по своей кнопке («Выпустить новую ссылку»): иначе отзыв
    отменялся бы при следующем открытии карточки.
    """
    content = content if content is not None else build_content(db, user_id)
    cur = active(db, user_id)
    if content is None:
        return cur
    if cur is not None and cur.fingerprint == fingerprint(content) and as_aware(cur.valid_until) > utcnow():
        return cur
    if cur is None and _candidate_opted_out(db, user_id):
        return None
    if cur is not None:
        _revoke(cur, reason)
    return issue(db, user_id, content, test_session_id=test_session_id)


def _candidate_opted_out(db: Session, user_id: uuid.UUID) -> bool:
    last = db.scalar(select(GradePassport).where(GradePassport.user_id == user_id)
                     .order_by(GradePassport.issued_at.desc()).limit(1))
    return bool(last and last.revoke_reason == "candidate_revoked")


def on_test_finished(db: Session, user_id: uuid.UUID, ts, *, previous_grade: str | None,
                     previous_direction: str | None, after_review: bool = False) -> GradePassport | None:
    """Хук после теста (finish_session) и после экспертной проверки (review.recompute): категория присвоена
    или подтверждена — выпуск или перевыпуск.

    Понижение грейда (пересдача на грейд ниже) — старый паспорт отзывается с причиной downgraded.
    after_review: пересчёт той же сессии по оценке эксперта (не новый тест) — прежний паспорт «заменён после
    экспертной проверки» (reviewed), а ссылку, которую кандидат отозвал сам, проверка эксперта не возвращает.
    """
    try:
        crypto.signing_key()  # неверный PASSPORT_SIGNING_KEY — до изменений в сессии: тест завершается, паспорта нет
        content = build_content(db, user_id)
    except Exception:  # noqa: BLE001
        log.exception("passport: не удалось подготовить паспорт после теста %s", getattr(ts, "id", None))
        return None
    profile = db.get(CandidateProfile, user_id)
    if profile is None or content is None:
        return None
    reason = "reviewed" if after_review else "superseded"
    if (previous_direction == profile.current_direction_id and previous_grade in GRADE_ORDER
            and profile.current_grade_id in GRADE_ORDER
            and GRADE_ORDER.index(profile.current_grade_id) < GRADE_ORDER.index(previous_grade)):
        reason = "downgraded"
    if not after_review and active(db, user_id) is None and _candidate_opted_out(db, user_id):
        # кандидат отозвал ссылку сам: новый тест — новый паспорт (отзыв относился к старому составу)
        return issue(db, user_id, content, test_session_id=ts.id)
    return ensure_current(db, user_id, reason=reason, test_session_id=ts.id, content=content)


def revoke_user(db: Session, user_id: uuid.UUID, reason: str) -> int:
    """Отзывает все действующие паспорта кандидата (удаление учётной записи, аннулирование, понижение)."""
    if reason not in REASONS:
        raise ValueError(reason)
    rows = db.scalars(select(GradePassport).where(GradePassport.user_id == user_id,
                                                  GradePassport.revoked_at.is_(None))).all()
    now = utcnow()
    for r in rows:
        _revoke(r, reason, now)
    return len(rows)


def candidate_revoke(db: Session, user_id: uuid.UUID) -> GradePassport | None:
    cur = active(db, user_id)
    if cur is None:
        raise api_error(404, "passport_not_found", "Действующего паспорта нет")
    _revoke(cur, "candidate_revoked")
    return cur


def candidate_reissue(db: Session, user_id: uuid.UUID) -> GradePassport:
    content = build_content(db, user_id)
    if content is None:
        raise api_error(409, "category_required", "Паспорт выпускается после присвоения категории по тесту")
    cur = active(db, user_id)
    if cur is not None:
        _revoke(cur, "candidate_revoked")
    return issue(db, user_id, content)


# ------------------------------------------------------------------ ключи и проверка

def known_keys(db: Session) -> dict[str, dict]:
    """kid → JWK: ключи из реестра, текущий ключ процесса и выведенные из оборота (PASSPORT_RETIRED_PUBLIC_KEYS)."""
    cur = crypto.signing_key()
    out: dict[str, dict] = {}
    for k in db.scalars(select(PassportKey).order_by(PassportKey.created_at)).all():
        out[k.kid] = crypto.jwk(k.public_key, test_key=k.test_key, retired=k.kid != cur.kid)
    for pub in crypto.retired_public_keys():
        kid = crypto.kid_for(pub)
        out.setdefault(kid, crypto.jwk(pub, retired=True))
    out[cur.kid] = crypto.jwk(cur.public_b64, test_key=cur.test_key)
    return out


def verify_document(db: Session, document: str, signature: str, kid: str) -> dict:
    keys = known_keys(db)
    k = keys.get(kid)
    return {"kid": kid, "kid_known": k is not None, "test_key": bool(k and k.get("test_key")),
            "signature_valid": bool(k and crypto.verify(document, signature, k["x"]))}


def evaluate(db: Session, p: GradePassport, now: datetime | None = None) -> dict:
    """Статус по реестру: valid | revoked | expired | invalid_signature (приоритет — подпись)."""
    now = now or utcnow()
    sig = verify_document(db, p.document, p.signature, p.kid)
    try:
        claims = crypto_json(p.document)
        consistent = claims.get("id") == p.id and claims.get("kid") == p.kid
    except ValueError:
        claims, consistent = {}, False
    reason = p.revoke_reason
    if p.revoked_at is None and (p.user_id is None or db.get(User, p.user_id) is None):
        reason = "account_deleted"  # SQLite без внешних ключей: строка пользователя удалена, ссылка осталась
    if not (sig["signature_valid"] and consistent):
        state = "invalid_signature"
    elif p.revoked_at is not None or reason == "account_deleted":
        state = "revoked"
    elif as_aware(p.valid_until) <= now:
        state = "expired"
    else:
        state = "valid"
    return {"state": state, "title": STATE_TITLES[state],
            "reason": reason if state == "revoked" else None,
            "reason_title": REASONS.get(reason) if state == "revoked" else None,
            "revoked_at": _iso(p.revoked_at) if state == "revoked" else None,
            "issued_at": _iso(p.issued_at), "valid_until": _iso(p.valid_until), "checked_at": _iso(now),
            "signature_valid": sig["signature_valid"], "kid_known": sig["kid_known"], "test_key": sig["test_key"]}


def crypto_json(document: str) -> dict:
    out = json.loads(document)
    if not isinstance(out, dict):
        raise ValueError("document")
    return out


def public_view(db: Session, p: GradePassport) -> dict:
    """GET /api/passport/<id>: подписанный документ (строкой и разобранный), подпись, статус по реестру, ключ."""
    try:
        claims = crypto_json(p.document)
    except ValueError:
        claims = {}
    keys = known_keys(db)
    return {
        "passport": claims,
        "document": p.document,
        "signature": {"alg": crypto.ALG, "kid": p.kid, "value": p.signature},
        "status": evaluate(db, p),
        "keys": [keys[p.kid]] if p.kid in keys else [],
        "verify_url": verify_url(p.id),
        "canonicalization": "json.dumps(passport, ensure_ascii=False, sort_keys=True, separators=(',', ':')), "
                            "UTF-8; дробь с нулевой дробной частью (1.0) записывается как целое (1)",
    }


def _preliminary_reason(db: Session, user_id: uuid.UUID) -> str | None:
    b = load_bundles(db, [user_id]).get(user_id)
    if b is None:
        return None
    t = b.test.value if b.test else {}
    if (t or {}).get("pending_review"):
        return (f"Открытых ответов теста на проверке эксперта — {int(t['pending_review'])}: до проверки грейд в паспорте "
                "«предварительный», после неё паспорт перевыпустится сам.")
    if b.grade_status == "provisional":
        return "Junior — предварительно: вероятность уровня ниже порога подтверждения; подтвердит короткое дотестирование."
    return "Уровень Lead/Principal по тесту — предварительно: точность различения у верхних уровней ниже цели."


def owner_view(db: Session, p: GradePassport | None, user_id: uuid.UUID) -> dict:
    hist = db.scalars(select(GradePassport).where(GradePassport.user_id == user_id)
                      .order_by(GradePassport.issued_at.desc()).limit(10)).all()
    content = build_content(db, user_id)
    return {
        "active": ({**public_view(db, p), "id": p.id} if p is not None else None),
        "eligible": content is not None,
        # FIX7 п. 6: почему паспорт «предварительный» — тот же источник, что у экрана «Категория» (passport_status)
        "preliminary_reason": _preliminary_reason(db, user_id) if content and content["grade_status"] == "preliminary" else None,
        "opted_out": p is None and _candidate_opted_out(db, user_id),
        "history": [{"id": h.id, "category_id": h.category_id, "grade_status": h.grade_status,
                     "issued_at": _iso(h.issued_at), "valid_until": _iso(h.valid_until),
                     "revoked_at": _iso(h.revoked_at), "reason": h.revoke_reason,
                     "reason_title": REASONS.get(h.revoke_reason or "")} for h in hist],
    }


def brief(db: Session, p: GradePassport) -> dict:
    """Короткая сводка для карточки работодателя и PDF: id, ссылка, статус."""
    ev = evaluate(db, p)
    return {"id": p.id, "url": verify_url(p.id), "path": f"/verify/{p.id}", "state": ev["state"],
            "title": ev["title"], "grade_status": p.grade_status, "issued_at": ev["issued_at"],
            "valid_until": ev["valid_until"], "test_key": ev["test_key"],
            # KF1 «Паспорт-щит»: ключ подписи и QR — для значка «Паспорт Ed25519: действует» и показа QR
            "kid": p.kid, "alg": crypto.ALG, "signature_valid": ev["signature_valid"],
            "qr_path": f"/api/passport/{p.id}/qr.svg"}


def for_pdf(db: Session, user_id: uuid.UUID) -> dict | None:
    """Сводка действующего паспорта для PDF-профиля (выпускает, если положен). Сбой паспорта не ломает PDF."""
    try:
        p = ensure_current(db, user_id)
        db.commit()
        return brief(db, p) if p is not None else None
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("passport: сводка для PDF не собралась")
        return None


# ------------------------------------------------------------------ KF1 «Паспорт-щит»: офлайн-проверка и демо жюри

def offline_bundle(db: Session, p: GradePassport) -> dict:
    """Файл для офлайн-проверки: паспорт, подпись, открытый ключ JWKS и порядок проверки без обращения к серверу."""
    view = public_view(db, p)
    s = get_settings()
    base = s.public_base_url.rstrip("/")
    return {
        "passport": view["passport"],
        "document": view["document"],  # подписанная строка (канонический JSON паспорта) — проверяется как есть
        "signature": view["signature"],
        "jwks": {"keys": view["keys"]},
        "jwks_url": f"{base}/.well-known/jwks.json",
        "verify_url": view["verify_url"],
        "status_at_download": view["status"],
        "canonicalization": view["canonicalization"],
        "how_to_verify": [
            "1. Возьмите поле document (канонический JSON паспорта: ключи по алфавиту, без пробелов, UTF-8) — оно "
            "совпадает с полем passport.",
            "2. Возьмите ключ из jwks.keys с тем же kid, что в signature.kid "
            "(поле x — открытый ключ Ed25519, base64url).",
            "3. Проверьте signature.value (base64url) по алгоритму Ed25519 любой библиотекой: "
            "обращение к серверу не нужно.",
            "4. Статус отзыва — онлайн: verify_url или POST /api/passport/verify.",
        ],
        "why_ed25519": "HMAC-токен может проверить только выдавший сервер (секрет у него); асимметричную подпись "
                       "Ed25519 проверяет любой по открытому ключу JWKS.",
    }


def demo_user_id(db: Session, sid: str = "") -> uuid.UUID | None:
    """Демо-кандидат жюри (Мария Королёва) общего демо или песочницы sid."""
    from app.modules.jury import scope

    email = scope.emails(sid)["candidate"]
    return db.scalar(select(User.id).where(User.email == email))


def demo_view(db: Session, user_id: uuid.UUID) -> dict:
    """Паспорт демо-кандидата для панели жюри: выпускается при первом запросе (если кандидат не отозвал ссылку)."""
    p = ensure_current(db, user_id)
    db.commit()
    ov = owner_view(db, p, user_id)
    return {"passport": brief(db, p) if p is not None else None,
            "opted_out": ov["opted_out"], "eligible": ov["eligible"],
            "jwks_url": "/.well-known/jwks.json", "jwks_api_url": "/api/.well-known/jwks.json",
            "history": ov["history"][:5]}
