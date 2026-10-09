"""Проверка с живыми пользователями: приглашения, согласие, привязка учётной записи, события, анкета, отзыв."""
from __future__ import annotations

import hashlib
import re
import secrets
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import as_aware, utcnow
from app.core.enums import UserRole
from app.core.errors import api_error
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.matching.models import EmployerNeed, SelectionVersion
from app.modules.profiles.models import CandidateProfile, Company, EmployerProfile
from app.modules.profiles.refs import new_public_ref
from app.modules.study import path as P
from app.modules.study import stats, texts
from app.modules.study.models import StudyAnswer, StudyEvent, StudyParticipant

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # без 0/O и 1/I (как у ссылок кандидатов)
CODE_LEN = 12  # 32^12 = 2^60 вариантов
QUICK_DOMAIN = "study.invalid"  # .invalid: письма таким учёткам не отправляются (notifications.mailer.notify)
EVENT_CAP = 3000  # событий на участника: защита базы от зацикленного клиента
TOP_K = 5


# ----------------------------------------------------------------------------- код-ссылка

def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))


def normalize_code(code: str) -> str | None:
    c = re.sub(r"[\s\-]", "", (code or "")).upper()
    return c if len(c) == CODE_LEN and all(ch in ALPHABET for ch in c) else None


def pretty(code: str) -> str:
    return "-".join(code[i:i + 4] for i in range(0, CODE_LEN, 4))


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def invite_url(code: str, base_url: str | None = None) -> str:
    base = (base_url or get_settings().public_base_url or "").rstrip("/")
    return f"{base}/study/{pretty(code)}"


# ----------------------------------------------------------------------------- приглашения

def _next_label(db: Session, role: str, is_test: bool) -> str:
    prefix = ("Т" if is_test else "") + ("К" if role == "candidate" else "Р")
    n = db.scalar(select(func.count()).select_from(StudyParticipant).where(StudyParticipant.label.like(f"{prefix}-%"))) or 0
    return f"{prefix}-{n + 1:02d}"


def create_invites(db: Session, role: str, n: int, *, batch: str = "", mode: str = "register", is_test: bool = False,
                   base_url: str | None = None) -> list[dict]:
    """Выпускает n персональных ссылок. Код в базе — только хеш: показывается один раз, потеряли — выпустите новый."""
    if role not in texts.ROLES:
        raise api_error(422, "bad_role", "Роль участника — candidate или employer")
    if not 1 <= n <= 100:
        raise api_error(422, "bad_count", "За один раз можно выпустить от 1 до 100 ссылок")
    if mode not in ("register", "quick"):
        raise api_error(422, "bad_mode", "Режим входа — register или quick")
    out = []
    for _ in range(n):
        code = new_code()
        p = StudyParticipant(code_hash=code_hash(code), role=role, label=_next_label(db, role, is_test), batch=(batch or "")[:64],
                             mode=mode, is_test=is_test)
        db.add(p)
        db.flush()  # следующая метка считается по уже добавленным
        out.append({"label": p.label, "role": role, "mode": mode, "is_test": is_test, "batch": p.batch,
                    "code": pretty(code), "url": invite_url(code, base_url)})
    db.commit()
    return out


def find(db: Session, code: str) -> StudyParticipant:
    c = normalize_code(code)
    p = db.scalar(select(StudyParticipant).where(StudyParticipant.code_hash == code_hash(c))) if c else None
    if p is None:
        raise api_error(404, "invite_not_found", "Ссылка недействительна. Попросите новую у того, кто её прислал")
    return p


def _state(p: StudyParticipant) -> str:
    if p.withdrawn_at:
        return "withdrawn"
    if not p.is_active:
        return "closed"
    return "started" if p.started_at else "new"


def invite_view(db: Session, p: StudyParticipant) -> dict:
    """Что видит человек на странице приглашения (без входа): роль, шаги, согласие. Имён и цифр других участников нет."""
    if p.opened_at is None:
        p.opened_at = utcnow()
        db.commit()
    return {"role": p.role, "role_title": texts.ROLE_TITLE[p.role], "mode": p.mode, "state": _state(p), "minutes": 20,
            "steps": [{"key": k, "title": t, "hint": texts.STEP_HINT[(p.role, k)]}
                      for k, t, _ in texts.PATH[p.role] if not (p.mode == "quick" and k == "register")],
            "consent": {"version": texts.CONSENT_VERSION, "title": texts.CONSENT_TITLE, "text": texts.CONSENT_TEXT,
                        "collected": list(texts.COLLECTED), "not_collected": list(texts.NOT_COLLECTED)}}


def _quick_account(db: Session, role: str) -> User:
    """Временная учётная запись без имени и почты (вход только по ссылке): письма ей не уходят (.invalid)."""
    u = User(email=f"study-{secrets.token_hex(6)}@{QUICK_DOMAIN}", password_hash=hash_password(secrets.token_urlsafe(24)),
             role=UserRole(role), is_email_verified=True, email_verified_at=utcnow(), is_demo=False)
    db.add(u)
    db.flush()
    if role == "candidate":
        db.add(CandidateProfile(user_id=u.id, full_name=None, public_ref=new_public_ref(db)))
    else:
        c = Company(name="Компания участника проверки", created_by=u.id, contact_email=u.email)
        db.add(c)
        db.flush()
        db.add(EmployerProfile(user_id=u.id, company_id=c.id, full_name=None))
    return u


def start(db: Session, p: StudyParticipant, consent: bool) -> tuple[StudyParticipant, User | None]:
    """Согласие и начало пути. Повтор — безопасен. Режим quick: создаёт временную учётную запись и возвращает её для входа."""
    if p.withdrawn_at:
        raise api_error(410, "withdrawn", "Участие отозвано, ссылка больше не действует")
    if not p.is_active:
        raise api_error(410, "invite_closed", "Приглашение закрыто")
    if not consent:
        raise api_error(422, "consent_required", "Нужно согласие на участие и обезличенную статистику")
    now = utcnow()
    if p.started_at is None:
        p.consent_at = p.started_at = now
        p.consent_version = texts.CONSENT_VERSION
    user = None
    if p.mode == "quick":
        user = db.get(User, p.user_id) if p.user_id else None
        if user is None:
            user = _quick_account(db, p.role)
            p.user_id, p.joined_at = user.id, now
    db.commit()
    return p, user


# ----------------------------------------------------------------------------- участник по учётной записи

def participant_of(db: Session, user: User) -> StudyParticipant | None:
    return db.scalar(select(StudyParticipant).where(StudyParticipant.user_id == user.id, StudyParticipant.withdrawn_at.is_(None)))


def join(db: Session, user: User, code: str) -> StudyParticipant:
    """Привязывает вошедшего пользователя к приглашению (после регистрации или входа по ссылке)."""
    p = find(db, code)
    if p.withdrawn_at:
        raise api_error(410, "withdrawn", "Участие отозвано, ссылка больше не действует")
    if not p.is_active:
        raise api_error(410, "invite_closed", "Приглашение закрыто")
    if p.started_at is None:
        raise api_error(409, "consent_required", "Сначала откройте ссылку приглашения и дайте согласие")
    if user.role.value != p.role:
        raise api_error(409, "role_mismatch", f"Приглашение для роли «{texts.ROLE_TITLE[p.role]}», а вы вошли иначе: "
                                              "зарегистрируйтесь по ссылке заново")
    if user.is_demo:
        raise api_error(403, "demo_account", "Демо-учётки жюри в проверке не участвуют")
    if p.user_id == user.id:
        return p
    if p.user_id is not None:
        raise api_error(409, "invite_taken", "Эта ссылка уже привязана к другой учётной записи")
    other = db.scalar(select(StudyParticipant.id).where(StudyParticipant.user_id == user.id))
    if other is not None:
        raise api_error(409, "already_participant", "Эта учётная запись уже участвует по другой ссылке")
    p.user_id, p.joined_at = user.id, utcnow()
    db.commit()
    return p


def me(db: Session, user: User) -> dict:
    p = participant_of(db, user)
    if p is None:
        return {"active": False}
    d = P.derive(db, p)
    ans = P.answered(db, p)
    keys = d["keys"]
    defs = {k: (t, link) for k, t, link in texts.PATH[p.role]}
    rows = []
    for k in keys:
        s = d["steps"][k]
        rows.append({"key": k, "title": defs[k][0], "hint": texts.STEP_HINT[(p.role, k)], "link": defs[k][1],
                     "done": s["at"] is not None, "skipped": s["skipped"], "at": s["at"].isoformat() if s["at"] else None})
    started = as_aware(p.started_at)
    return {"active": True, "role": p.role, "mode": p.mode, "steps": rows, "current": d["current"], "path_done": d["path_done"],
            "answered": ans is not None, "elapsed_s": int((utcnow() - started).total_seconds()) if started else 0,
            "target_min": 20, "survey_url": "/study/survey"}


# ----------------------------------------------------------------------------- события экранов и ошибок

def record_event(db: Session, user: User, kind: str, key: str, status: int | None = None, code: str | None = None) -> bool:
    p = participant_of(db, user)
    if p is None or p.started_at is None or P.answered(db, p) is not None:
        return False  # не участник или анкета уже сдана: ничего не пишем
    k = P.norm_key(key)
    if k is None or k.startswith("/study/") and k != "/study/survey":
        return False
    n = db.scalar(select(func.count()).select_from(StudyEvent).where(StudyEvent.participant_id == p.id)) or 0
    if n >= EVENT_CAP:
        return False
    now = utcnow()
    last = db.scalar(select(StudyEvent).where(StudyEvent.participant_id == p.id).order_by(StudyEvent.at.desc()).limit(1))
    if last is not None and last.kind == kind and last.key == k and last.status == status \
            and (now - as_aware(last.at)).total_seconds() < 1.0:
        return False
    db.add(StudyEvent(participant_id=p.id, kind=kind, key=k, status=status if kind == "error" else None,
                      code=(re.sub(r"[^A-Za-z0-9_.\-]", "", code or "")[:64] or None) if kind == "error" else None, at=now))
    p.last_seen_at = now
    db.commit()
    return True


# ----------------------------------------------------------------------------- анкета

def top5(db: Session, user: User) -> dict | None:
    """Первые пять кандидатов последней подборки работодателя — то, что он оценивает в анкете (порядок как в выдаче)."""
    v = db.scalar(select(SelectionVersion).join(EmployerNeed, EmployerNeed.id == SelectionVersion.need_id)
                  .where(EmployerNeed.created_by == user.id).order_by(SelectionVersion.created_at.desc()).limit(1))
    if v is None or not v.results:
        return None
    shown = []
    for r in v.results[:TOP_K]:
        c = r.get("card") or {}
        cat = (c.get("category") or {}).get("title") or ((c.get("claimed") or {}).get("title"))
        reasons = [str(x.get("text")) for x in (r.get("reasons") or []) if isinstance(x, dict) and x.get("text")][:3]
        shown.append({"ref": r.get("ref"), "rank": r.get("rank") or len(shown) + 1, "category": cat,
                      "status": r.get("grade_status") or (c.get("status") or {}).get("status"), "reasons": reasons})
    return {"need_id": str(v.need_id), "version": v.version, "algorithm": v.algorithm_version, "shown": shown}


def form(db: Session, user: User) -> dict:
    p = participant_of(db, user)
    if p is None:
        raise api_error(404, "not_participant", "Эта учётная запись не участвует в проверке")
    d = P.derive(db, p)
    ans = P.answered(db, p)
    exposed = d["steps"].get("result" if p.role == "candidate" else "selection", {}).get("at") is not None
    sel = top5(db, user) if p.role == "employer" and exposed else None
    return {"role": p.role, "path_done": d["path_done"], "exposed": exposed,
            "sus": {"items": list(texts.SUS_ITEMS), "scale": list(texts.SUS_SCALE)},
            "rel": {"scale": list(texts.REL_SCALE), "threshold": texts.REL_THRESHOLD, "selection": sel},
            "belief": {"q": texts.BELIEF_Q[p.role]},
            "grade_fit": ({"q": texts.GRADE_FIT_Q, "options": texts.GRADE_FIT} if p.role == "candidate" else None),
            "tags": texts.BLOCKER_TAGS, "text_max": texts.TEXT_MAX,
            "answers": ({"sus": ans.sus, "ratings": ans.ratings, "belief": ans.belief, "grade_fit": ans.grade_fit,
                         "tags": ans.tags, "comment": ans.comment} if ans else None)}


def clean_comment(text: str | None) -> str | None:
    """Комментарий — только по делу: контакты (почта, телефон, ссылки, ники) убираются до сохранения; исходный текст не хранится."""
    t = (text or "").strip()[:texts.TEXT_MAX]
    if not t:
        return None
    from app.modules.contact.masking import mask_contacts
    from app.modules.resume.pii import redact

    t, _ = mask_contacts(t)
    t = redact(t, use_ner=False).text
    return t.strip() or None


def submit(db: Session, user: User, *, sus: list[int], ratings: list[dict] | None, belief: int | None, grade_fit: str | None,
           tags: list[str] | None, comment: str | None) -> dict:
    p = participant_of(db, user)
    if p is None:
        raise api_error(404, "not_participant", "Эта учётная запись не участвует в проверке")
    try:
        stats.sus_score(sus)
    except ValueError:
        raise api_error(422, "bad_sus", "Ответьте на все 10 вопросов шкалы: от 1 до 5") from None
    d = P.derive(db, p)
    exposed = d["steps"].get("result" if p.role == "candidate" else "selection", {}).get("at") is not None
    sel, rated = None, []
    if p.role == "employer" and exposed:
        sel = top5(db, user)
        if sel and sel["shown"]:
            by_ref = {x["ref"]: x for x in sel["shown"]}
            got = {}
            for r in ratings or []:
                ref, val = r.get("ref"), r.get("rating")
                if ref not in by_ref or isinstance(val, bool) or not isinstance(val, int) or not 1 <= val <= 5 or ref in got:
                    raise api_error(422, "bad_rating", "Оценка — число от 1 до 5 для каждого из показанных кандидатов")
                got[ref] = val
            if set(got) != set(by_ref):
                raise api_error(422, "ratings_incomplete", "Оцените всех показанных кандидатов")
            rated = [{"ref": ref, "rank": by_ref[ref]["rank"], "rating": got[ref]} for ref in by_ref]
    if belief is not None and (isinstance(belief, bool) or not 1 <= belief <= 5):
        raise api_error(422, "bad_belief", "Доверие к грейду — число от 1 до 5")
    if grade_fit is not None and grade_fit not in texts.GRADE_FIT:
        raise api_error(422, "bad_grade_fit", "Допустимо: занижен, соответствует, завышен")
    if not exposed:  # вопросов о грейде и подборке человек не видел — ответов нет
        belief, grade_fit = None, None
    if p.role != "candidate":
        grade_fit = None
    tag_list = [t for t in dict.fromkeys(tags or []) if t in texts.BLOCKER_TAGS]
    row = P.answered(db, p)
    if row is None:
        row = StudyAnswer(participant_id=p.id)
        db.add(row)
    row.sus, row.ratings, row.belief, row.grade_fit, row.tags = list(sus), rated, belief, grade_fit, tag_list
    row.selection = ({"need_id": sel["need_id"], "version": sel["version"], "algorithm": sel["algorithm"],
                      "shown": len(sel["shown"])} if sel and rated else None)
    row.comment, row.path_done, row.submitted_at = clean_comment(comment), d["path_done"], utcnow()
    db.commit()
    return {"ok": True, "sus_score": stats.sus_score(sus), "path_done": d["path_done"]}


def withdraw(db: Session, user: User) -> dict:
    """Отзыв согласия: события и анкета удаляются, связь с учётной записью снимается, ссылка перестаёт работать."""
    p = participant_of(db, user)
    if p is None:
        raise api_error(404, "not_participant", "Эта учётная запись не участвует в проверке")
    db.execute(delete(StudyEvent).where(StudyEvent.participant_id == p.id))
    db.execute(delete(StudyAnswer).where(StudyAnswer.participant_id == p.id))
    p.withdrawn_at, p.user_id, p.is_active = utcnow(), None, False
    db.commit()
    return {"ok": True}


def close_invites(db: Session, *, batch: str | None = None, label: str | None = None) -> int:
    """Закрывает неначатые приглашения (по пачке или метке): ссылка перестаёт работать. Начатые не трогает."""
    q = select(StudyParticipant).where(StudyParticipant.started_at.is_(None), StudyParticipant.is_active.is_(True))
    if batch is not None:
        q = q.where(StudyParticipant.batch == batch)
    if label:
        q = q.where(StudyParticipant.label == label)
    rows = list(db.scalars(q))
    for p in rows:
        p.is_active = False
    db.commit()
    return len(rows)
