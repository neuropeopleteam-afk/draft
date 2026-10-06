"""Эксперты панели: приглашения по ссылке, вход без регистрации, назначение, прогресс, сохранение оценок."""
from __future__ import annotations

import hashlib
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.enums import UserRole
from app.core.errors import api_error
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.experts import pack as P
from app.modules.experts.models import ExpertItem, ExpertLabel, ExpertPanelist

INVITE_DOMAIN = "panel.example.com"  # служебные почты экспертов (RFC 2606: письма туда не уходят)
FLAGS = ("none", "copy", "injection", "offtopic")
MINUTES = {"A": 0.6, "B": 1.5, "C": 1.0}  # ориентир темпа на объект (протокол: ~40 с на пару, 1,5–2 мин на ответ)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def invite_url(token: str) -> str:
    return f"{(get_settings().public_base_url or '').rstrip('/')}/expert-invite/{token}"


def create_invite(db: Session, code: str, *, slot: str | None = None, team_size: int = 3, name: str | None = None,
                  profile: str | None = None, rotate: bool = False) -> dict:
    """Создаёт эксперта (или перевыпускает ссылку) и возвращает персональную ссылку. Токен в базе — только хеш."""
    code = code.strip().upper()
    slot = (slot or code).upper()
    if slot not in P.SLOTS:
        raise api_error(422, "bad_slot", "Слот назначения — E1, E2 или E3")
    if not P.ensure_pack(db):
        raise api_error(409, "pack_not_ready", "Пакет разметки не собран: нет демо-данных (make seed)")
    token = secrets.token_urlsafe(24)
    pan = db.scalar(select(ExpertPanelist).where(ExpertPanelist.code == code, ExpertPanelist.is_demo.is_(False)))
    if pan is None:
        u = User(email=f"{code.lower()}-{secrets.token_hex(4)}@{INVITE_DOMAIN}",
                 password_hash=hash_password(secrets.token_urlsafe(24)), role=UserRole.expert,
                 is_email_verified=True, email_verified_at=utcnow(), is_demo=False)
        db.add(u)
        db.flush()
        pan = ExpertPanelist(code=code, slot=slot, team_size=team_size, display_name=name, profile=profile,
                             user_id=u.id, token_hash=token_hash(token), pack=P.PACK,
                             assignment=P.assignment(db, slot, team_size))
        db.add(pan)
        created = True
    else:
        if not rotate:
            raise api_error(409, "expert_exists", f"Эксперт {code} уже приглашён; новая ссылка — с параметром rotate")
        pan.token_hash = token_hash(token)
        pan.is_active = True
        if name:
            pan.display_name = name
        if profile:
            pan.profile = profile
        created = False
    db.commit()
    return {"code": code, "slot": pan.slot, "team_size": pan.team_size, "created": created, "token": token,
            "url": invite_url(token), "assigned": {k: len(v) for k, v in pan.assignment.items()}}


def enter(db: Session, token: str) -> tuple[User, ExpertPanelist]:
    pan = db.scalar(select(ExpertPanelist).where(ExpertPanelist.token_hash == token_hash(token or "")))
    if pan is None or not pan.is_active:
        raise api_error(404, "invite_not_found", "Ссылка недействительна. Попросите новую у того, кто её прислал")
    user = db.get(User, pan.user_id)
    if user is None or not user.is_active:
        raise api_error(404, "invite_not_found", "Ссылка недействительна. Попросите новую у того, кто её прислал")
    user.last_login_at = pan.last_seen_at = utcnow()
    db.commit()
    return user, pan


def panelist_for(db: Session, user: User, create_demo: bool = True) -> ExpertPanelist | None:
    """Эксперт панели для текущего пользователя. Демо-эксперт жюри получает демо-назначение (в метрики не входит)."""
    pan = db.scalar(select(ExpertPanelist).where(ExpertPanelist.user_id == user.id))
    if pan is not None or not create_demo:
        return pan
    if not (user.is_demo or user.role == UserRole.admin):
        return None
    if not P.ensure_pack(db):
        return None
    pan = ExpertPanelist(code="DEMO", slot="DEMO", team_size=1, display_name="Демо-эксперт", user_id=user.id,
                         token_hash=None, pack=P.PACK, assignment=P.assignment(db, "DEMO"), is_demo=True)
    db.add(pan)
    db.commit()
    return pan


def _items(db: Session, pan: ExpertPanelist, kind: str) -> list[ExpertItem]:
    keys = pan.assignment.get(kind) or []
    rows = {i.key: i for i in db.scalars(select(ExpertItem).where(ExpertItem.pack == pan.pack, ExpertItem.key.in_(keys)))}
    return [rows[k] for k in keys if k in rows]


def _labels(db: Session, pan: ExpertPanelist) -> dict[uuid.UUID, ExpertLabel]:
    return {lb.item_id: lb for lb in db.scalars(select(ExpertLabel).where(ExpertLabel.panelist_id == pan.id))}


def progress(db: Session, pan: ExpertPanelist) -> dict:
    labels = _labels(db, pan)
    out = {}
    for kind in ("A", "B", "C"):
        items = _items(db, pan, kind)
        done = sum(1 for i in items if i.id in labels)
        out[kind] = {"total": len(items), "done": done, "minutes_left": round(MINUTES[kind] * (len(items) - done))}
    return out


def me(db: Session, pan: ExpertPanelist) -> dict:
    pan.last_seen_at = utcnow()
    db.commit()
    return {"code": pan.code, "name": pan.display_name, "is_demo": pan.is_demo, "pack": pan.pack,
            "instructions_ack_at": pan.instructions_ack_at.isoformat() if pan.instructions_ack_at else None,
            "progress": progress(db, pan)}


def items_for(db: Session, pan: ExpertPanelist, kind: str) -> dict:
    labels = _labels(db, pan)
    rows = []
    for n, it in enumerate(_items(db, pan, kind), start=1):
        lb = labels.get(it.id)
        rows.append({"id": str(it.id), "n": n, "group": it.grp if kind != "B" else None, **it.payload,
                     "label": ({**lb.value, "comment": lb.comment or ""} if lb else None)})
    return {"kind": kind, "items": rows, "progress": progress(db, pan)[kind]}


def _validate(kind: str, it: ExpertItem, v: dict) -> dict:
    def bad(msg: str):
        raise api_error(422, "bad_label", msg)

    if kind == "A":
        r = v.get("relevance")
        if not isinstance(r, int) or isinstance(r, bool) or r not in (0, 1, 2, 3):
            bad("Оценка соответствия — целое число от 0 до 3")
        return {"relevance": r, "must_have_missing": str(v.get("must_have_missing") or "")[:500]}
    if kind == "B":
        crit = [c["id"] for c in (it.payload.get("rubric") or {}).get("criteria", [])]
        got = v.get("criteria") or {}
        if not isinstance(got, dict) or set(got) != set(crit):
            bad("Оцените каждый критерий рубрики")
        vals = {}
        for k in crit:
            x = got[k]
            if isinstance(x, bool) or not isinstance(x, (int, float)) or float(x) not in (0.0, 0.5, 1.0):
                bad("Оценка критерия — 0, 0,5 или 1")
            vals[k] = float(x)
        h = v.get("holistic")
        if not isinstance(h, int) or isinstance(h, bool) or h not in (0, 1, 2, 3):
            bad("Общая оценка — целое число от 0 до 3")
        flag = v.get("flag") or "none"
        if flag not in FLAGS:
            bad("Флаг — none, copy, injection или offtopic")
        return {"criteria": vals, "holistic": h, "flag": flag}
    if kind == "C":
        floor = int(it.payload.get("floor") or 0)
        out = {}
        for b in ("junior_middle", "middle_senior"):
            x = v.get(b)
            if not isinstance(x, int) or isinstance(x, bool) or not 0 <= x <= 100 or x % 5:
                bad("Доля решивших — число от 0 до 100 с шагом 5")
            if x < floor:
                bad(f"Для задания с выбором из четырёх вариантов — не ниже {floor}: столько дало бы угадывание")
            out[b] = x
        if out["middle_senior"] < out["junior_middle"]:
            bad("Пограничный Senior не может решать хуже пограничного Middle")
        c = v.get("confidence")
        if c not in (1, 2, 3):
            bad("Уверенность — 1, 2 или 3")
        out["confidence"] = c
        return out
    bad("Неизвестный тип объекта")
    return {}


def save_label(db: Session, pan: ExpertPanelist, item_id: uuid.UUID, value: dict, comment: str | None,
               seconds: int | None) -> dict:
    it = db.get(ExpertItem, item_id)
    if it is None or it.pack != pan.pack or it.key not in (pan.assignment.get(it.kind) or []):
        raise api_error(404, "item_not_found", "Нет такого объекта в вашем назначении")
    val = _validate(it.kind, it, value or {})
    lb = db.scalar(select(ExpertLabel).where(ExpertLabel.panelist_id == pan.id, ExpertLabel.item_id == it.id))
    if lb is None:
        lb = ExpertLabel(panelist_id=pan.id, item_id=it.id, value=val, comment=(comment or "")[:2000] or None,
                         seconds=seconds)
        db.add(lb)
    else:
        lb.value, lb.comment = val, (comment or "")[:2000] or None
        if seconds:
            lb.seconds = (lb.seconds or 0) + seconds
    pan.last_seen_at = utcnow()
    db.commit()
    return {"saved": True, "item_id": str(it.id), "value": val, "progress": progress(db, pan)[it.kind]}


def ack_instructions(db: Session, pan: ExpertPanelist) -> dict:
    if pan.instructions_ack_at is None:
        pan.instructions_ack_at = utcnow()
        db.commit()
    return me(db, pan)


def panel_status(db: Session) -> list[dict]:
    """Обезличенный статус панели для /validation: коды, назначено, сделано, последняя активность (без имён)."""
    out = []
    for pan in db.scalars(select(ExpertPanelist).where(ExpertPanelist.is_demo.is_(False))
                          .order_by(ExpertPanelist.code)).all():
        pr = progress(db, pan)
        out.append({"code": pan.code, "active": pan.is_active, "started": any(v["done"] for v in pr.values()),
                    "progress": {k: {"done": v["done"], "total": v["total"]} for k, v in pr.items()},
                    "last_seen_at": pan.last_seen_at.isoformat() if pan.last_seen_at else None})
    return out
