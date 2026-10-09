"""Найм после принятия приглашения: правила переходов (покрыты tests/test_hiring.py).

Путь: приглашение принято (контакты открыты) → собеседование → оффер → исход найма. Каждый шаг — событие в истории
приглашения (invitation_events.kind), её видят обе стороны; этапы уходят в ATS работодателя (app.modules.hiring.ats)
и возвращаются обратным каналом (app.integrations.ats.stages).

Собеседование
* Работодатель предлагает 1–3 слота: дата и время (не раньше чем через SLOT_MIN_AHEAD и не позже SLOT_MAX_AHEAD_DAYS),
  длительность, формат (видеозвонок — нужна ссылка https, офис — адрес, телефон — без адреса). Одно активное
  собеседование на приглашение; новые слоты по активному заменяют прежние (перенос).
* Кандидат выбирает слот (только будущий) или просит другое время с комментарием — не больше RESCHEDULE_MAX раз.
* «Прошло» — только по назначенному собеседованию и после его начала. У демо-компаний (песочница жюри) ограничение
  по времени снято, как правило 90 дней у демо-учёток: путь проходится за минуту.
* Напоминание кандидату — push и письмо за REMIND_BEFORE до начала (app.modules.hiring.reminders), в кабинете —
  счётчик у раздела «Приглашения» и плашка на странице.

Оффер
* Сумма — не ниже «от» вилки приглашения (в одном основании НДФЛ), не выше OFFER_MAX_UP × «до»: оффер в пределах
  вилки или выше; дата выхода — от сегодня до START_MAX_DAYS; срок ответа — от часа до RESPOND_MAX_DAYS.
  Один открытый оффер на приглашение; работодатель может отозвать его и отправить новый.
* Кандидат принимает, отклоняет (исход «отказ кандидата» фиксируется сам) или делает встречное — механика
  встречного по приглашению (app.modules.contact): сумма выше предложенной и не выше 1,5 × оффера, одно ожидающее,
  не больше двух. Принятое работодателем встречное — оффер принят на сумме кандидата; отклонённое — оффер открыт.
* Срок ответа прошёл — оффер истёк (проверяется при чтении).

Исход найма (один на приглашение, окончательный)
* hired — «вышел на работу»: только по принятому офферу; rejected — «не прошёл» (решение работодателя);
  declined — «отказ кандидата». Открытые собеседование и оффер закрываются.

Права: кандидат — только свои приглашения, работодатель — только своей компании (чужое — 404 в роутере).
Найм ведётся только по принятому приглашению с открытыми контактами; отозванный доступ к контактам — пауза.
"""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta, timezone
import logging
import re
import secrets
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.db import as_aware, utcnow
from app.core.enums import InvitationStatus
from app.core.errors import api_error
from app.modules.contact.salary import basis_title, convert
from app.modules.contact.service import COUNTER_MAX, COUNTER_MAX_UP, rub
from app.modules.hiring.models import HiringInterview, HiringOffer, HiringOutcome
from app.modules.invitations.models import Invitation, InvitationEvent
from app.modules.profiles.models import Company

MSK = timezone(timedelta(hours=3), "МСК")  # без перехода на летнее время с 2014 года
SLOTS_MAX = 3
SLOT_MIN_AHEAD = timedelta(minutes=10)
SLOT_MAX_AHEAD_DAYS = 60
DURATIONS = (15, 240)
RESCHEDULE_MAX = 3
REMIND_BEFORE = timedelta(hours=24)
OFFER_MAX_UP = 3.0
START_MAX_DAYS = 180
RESPOND_MAX_DAYS = 30
FORMATS = {"video": "Видеозвонок", "phone": "Телефон", "office": "В офисе"}
ACTIVE = ("proposed", "reschedule", "scheduled")
OUTCOME_TITLES = {"hired": "Вышел на работу", "declined": "Отказ кандидата", "rejected": "Не прошёл"}
# Этап найма → этап на платформе для ATS (app.integrations.ats.stages.PLATFORM_STAGES)
ATS_STAGE = {"interview": "interview", "offer": "offer", "hired": "hired", "declined": "rejected",
             "rejected": "rejected"}
STAGE_TITLES = {"contact": "Контакты открыты", "slots": "Выбор времени собеседования",
                "reschedule": "Кандидат просит другое время", "interview": "Собеседование назначено",
                "interview_done": "Собеседование прошло", "offer": "Оффер отправлен",
                "offer_accepted": "Оффер принят", **OUTCOME_TITLES}
URL_RE = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.I)


# ------------------------------------------------------------------ форматирование

def msk(dt: datetime | None) -> str:
    """«10.10.2026, 11:00 МСК»."""
    if dt is None:
        return "—"
    return as_aware(dt).astimezone(MSK).strftime("%d.%m.%Y, %H:%M") + " МСК"


def ddmm(d: date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else "—"


def _log(db: Session, inv: Invitation, kind: str, actor: uuid.UUID | None, note: str | None = None) -> None:
    db.add(InvitationEvent(invitation_id=inv.id, from_status=inv.status, to_status=inv.status, actor_user_id=actor,
                           note=note, kind=kind))


def _clean(s: str | None) -> str | None:
    return (s or "").strip() or None


# ------------------------------------------------------------------ состояние

def interviews_of(db: Session, inv: Invitation) -> list[HiringInterview]:
    return list(db.scalars(select(HiringInterview).where(HiringInterview.invitation_id == inv.id)
                           .order_by(HiringInterview.created_at)).all())


def active_interview(db: Session, inv: Invitation) -> HiringInterview | None:
    return db.scalar(select(HiringInterview).where(HiringInterview.invitation_id == inv.id,
                                                   HiringInterview.status.in_(ACTIVE))
                     .order_by(HiringInterview.created_at.desc()).limit(1))


def offers_of(db: Session, inv: Invitation) -> list[HiringOffer]:
    return list(db.scalars(select(HiringOffer).where(HiringOffer.invitation_id == inv.id)
                           .order_by(HiringOffer.created_at)).all())


def outcome_of(db: Session, inv: Invitation) -> HiringOutcome | None:
    return db.scalar(select(HiringOutcome).where(HiringOutcome.invitation_id == inv.id))


def _expire(db: Session, o: HiringOffer | None) -> HiringOffer | None:
    """Срок ответа прошёл — оффер истёк (ленивая проверка при чтении)."""
    if o is not None and o.status == "sent" and as_aware(o.respond_until) <= utcnow():
        inv = db.get(Invitation, o.invitation_id)
        _close_counter(o, "withdrawn")
        o.status = "expired"
        _log(db, inv, "offer_expired", None, f"Срок ответа {msk(o.respond_until)} прошёл")
        db.commit()
    return o


def current_offer(db: Session, inv: Invitation) -> HiringOffer | None:
    o = db.scalar(select(HiringOffer).where(HiringOffer.invitation_id == inv.id)
                  .order_by(HiringOffer.created_at.desc()).limit(1))
    return _expire(db, o)


def stage_of(db: Session, inv: Invitation) -> str:
    """Этап найма для карточки и счётчиков."""
    oc = outcome_of(db, inv)
    if oc is not None:
        return oc.outcome
    o = current_offer(db, inv)
    if o is not None and o.status in ("sent", "accepted"):
        return "offer" if o.status == "sent" else "offer_accepted"
    iv = active_interview(db, inv)
    if iv is not None:
        return {"proposed": "slots", "reschedule": "reschedule", "scheduled": "interview"}[iv.status]
    if any(x.status == "done" for x in interviews_of(db, inv)):
        return "interview_done"
    return "contact"


def _company_demo(db: Session, inv: Invitation) -> bool:
    c = db.get(Company, inv.company_id)
    return bool(c and c.is_demo)


def guard(db: Session, inv: Invitation, side: str) -> None:
    """Найм — только по принятому приглашению с открытыми контактами и без итога."""
    if inv.status != InvitationStatus.accepted:
        raise api_error(409, "hiring_not_accepted", "Собеседование и оффер — после того, как кандидат примет приглашение")
    if inv.contacts_revealed_at is None:
        raise api_error(409, "hiring_contacts_revoked",
                        "Кандидат отозвал доступ к контактам — найм на паузе, пока он не вернёт доступ"
                        if side == "employer" else "Вы отозвали доступ к контактам — верните его, чтобы продолжить")
    oc = outcome_of(db, inv)
    if oc is not None:
        raise api_error(409, "hiring_closed", f"Найм по приглашению завершён: «{OUTCOME_TITLES[oc.outcome].lower()}»")


# ------------------------------------------------------------------ собеседование

def _slot_in(raw: dict, k: int, now: datetime) -> dict:
    at = raw.get("starts_at")
    if isinstance(at, str):
        try:
            at = datetime.fromisoformat(at.replace("Z", "+00:00"))
        except ValueError:
            raise api_error(422, "slot_time", f"Слот {k}: не удалось разобрать дату и время") from None
    if not isinstance(at, datetime):
        raise api_error(422, "slot_time", f"Слот {k}: укажите дату и время")
    at = at if at.tzinfo else at.replace(tzinfo=MSK)  # без часового пояса — московское время
    at = at.astimezone(timezone.utc).replace(second=0, microsecond=0)
    if at < now + SLOT_MIN_AHEAD:
        raise api_error(422, "slot_past", f"Слот {k}: время уже прошло или наступает меньше чем через 10 минут")
    if at > now + timedelta(days=SLOT_MAX_AHEAD_DAYS):
        raise api_error(422, "slot_far", f"Слот {k}: не дальше чем на {SLOT_MAX_AHEAD_DAYS} дней вперёд")
    dur = int(raw.get("duration_min") or 60)
    if not DURATIONS[0] <= dur <= DURATIONS[1]:
        raise api_error(422, "slot_duration", f"Слот {k}: длительность — от {DURATIONS[0]} до {DURATIONS[1]} минут")
    fmt = raw.get("format") or "video"
    if fmt not in FORMATS:
        raise api_error(422, "slot_format", f"Слот {k}: формат — видеозвонок, телефон или офис")
    place = _clean(raw.get("place"))
    if fmt == "video" and not (place and URL_RE.match(place)):
        raise api_error(422, "slot_link", f"Слот {k}: для видеозвонка нужна ссылка https://…")
    if fmt == "office" and not place:
        raise api_error(422, "slot_address", f"Слот {k}: для встречи в офисе укажите адрес")
    if place and len(place) > 500:
        raise api_error(422, "slot_place_long", f"Слот {k}: ссылка или адрес длиннее 500 символов")
    return {"id": secrets.token_hex(3), "starts_at": at.isoformat(), "duration_min": dur, "format": fmt,
            "place": place}


def propose(db: Session, inv: Invitation, actor: uuid.UUID, slots: list[dict], title: str | None,
            note: str | None) -> HiringInterview:
    guard(db, inv, "employer")
    if not 1 <= len(slots or []) <= SLOTS_MAX:
        raise api_error(422, "slots_count", f"Предложите от 1 до {SLOTS_MAX} слотов")
    now = utcnow()
    clean = [_slot_in(s, k, now) for k, s in enumerate(slots, 1)]
    if len({s["starts_at"] for s in clean}) != len(clean):
        raise api_error(422, "slots_duplicate", "Слоты повторяются — укажите разное время")
    clean.sort(key=lambda s: s["starts_at"])
    iv = active_interview(db, inv)
    kind = "interview_proposed"
    if iv is None:
        rnd = len(interviews_of(db, inv)) + 1
        iv = HiringInterview(invitation_id=inv.id, company_id=inv.company_id, candidate_user_id=inv.candidate_user_id,
                             created_by=actor, round=rnd, title=_clean(title) or (
                                 "Собеседование" if rnd == 1 else f"Собеседование, этап {rnd}"), status="proposed")
        db.add(iv)
    else:
        kind = "interview_moved" if iv.status == "scheduled" else "interview_proposed"
        iv.title = _clean(title) or iv.title
    iv.slots, iv.status, iv.note = clean, "proposed", _clean(note)
    iv.chosen_slot = iv.starts_at = iv.duration_min = iv.format = iv.place = None
    iv.reminded_at = None
    flag_modified(iv, "slots")
    _log(db, inv, kind, actor, f"{iv.title}: " + "; ".join(slot_text(s) for s in clean))
    db.commit()
    return iv


def slot_text(s: dict) -> str:
    at = datetime.fromisoformat(s["starts_at"])
    return f"{msk(at)}, {s['duration_min']} мин · {FORMATS.get(s['format'], s['format']).lower()}"


def _own_interview(db: Session, inv: Invitation, iid: uuid.UUID) -> HiringInterview:
    iv = db.get(HiringInterview, iid)
    if iv is None or iv.invitation_id != inv.id:
        raise api_error(404, "interview_not_found", "Собеседование не найдено")
    return iv


def choose(db: Session, inv: Invitation, actor: uuid.UUID, iid: uuid.UUID, slot_id: str) -> HiringInterview:
    iv = _own_interview(db, inv, iid)
    guard(db, inv, "candidate")
    if iv.status != "proposed":
        raise api_error(409, "interview_not_proposed", "Выбрать время можно, когда работодатель предложил слоты")
    s = next((x for x in iv.slots or [] if x.get("id") == slot_id), None)
    if s is None:
        raise api_error(422, "slot_unknown", "Такого слота нет — обновите страницу")
    at = datetime.fromisoformat(s["starts_at"])
    if at <= utcnow():
        raise api_error(409, "slot_past", "Это время уже прошло — выберите другой слот или попросите другое время")
    iv.status, iv.chosen_slot, iv.starts_at = "scheduled", s["id"], at
    iv.duration_min, iv.format, iv.place = s["duration_min"], s["format"], s.get("place")
    iv.candidate_note = None
    _log(db, inv, "interview_scheduled", actor, slot_text(s))
    db.commit()
    return iv


def request_other(db: Session, inv: Invitation, actor: uuid.UUID, iid: uuid.UUID, note: str | None) -> HiringInterview:
    iv = _own_interview(db, inv, iid)
    guard(db, inv, "candidate")
    if iv.status not in ("proposed", "scheduled"):
        raise api_error(409, "interview_not_open", "Попросить другое время можно по предложенному или назначенному "
                                                   "собеседованию")
    if iv.reschedules >= RESCHEDULE_MAX:
        raise api_error(409, "reschedule_limit", f"Другое время можно попросить не больше {RESCHEDULE_MAX} раз — "
                                                 "договоритесь в переписке")
    text = _clean(note)
    if not text:
        raise api_error(422, "reschedule_note", "Напишите, когда вам удобно — например, «после 18:00 в будни»")
    iv.status, iv.candidate_note, iv.reschedules = "reschedule", text[:500], iv.reschedules + 1
    iv.chosen_slot = iv.starts_at = None
    _log(db, inv, "interview_reschedule", actor, iv.candidate_note)
    db.commit()
    return iv


def mark_done(db: Session, inv: Invitation, actor: uuid.UUID, iid: uuid.UUID, note: str | None) -> HiringInterview:
    iv = _own_interview(db, inv, iid)
    guard(db, inv, "employer")
    if iv.status != "scheduled":
        raise api_error(409, "interview_not_scheduled", "Отметить «прошло» можно назначенное собеседование")
    if as_aware(iv.starts_at) > utcnow() and not _company_demo(db, inv):
        raise api_error(409, "interview_not_started", f"Собеседование назначено на {msk(iv.starts_at)} — "
                                                      "отметить «прошло» можно после начала")
    iv.status, iv.done_at, iv.result_note = "done", utcnow(), _clean(note)
    _log(db, inv, "interview_done", actor, iv.result_note)
    db.commit()
    return iv


def cancel(db: Session, inv: Invitation, actor: uuid.UUID, iid: uuid.UUID, note: str | None) -> HiringInterview:
    iv = _own_interview(db, inv, iid)
    guard(db, inv, "employer")
    if iv.status not in ACTIVE:
        raise api_error(409, "interview_not_open", "Собеседование уже прошло или отменено")
    iv.status, iv.result_note = "cancelled", _clean(note)
    _log(db, inv, "interview_cancelled", actor, iv.result_note)
    db.commit()
    return iv


# ------------------------------------------------------------------ оффер

def _date_in(v: date | str | None, field: str) -> date:
    if isinstance(v, str):
        try:
            v = date.fromisoformat(v[:10])
        except ValueError:
            raise api_error(422, field, "Не удалось разобрать дату") from None
    if not isinstance(v, date):
        raise api_error(422, field, "Укажите дату")
    return v


def send_offer(db: Session, inv: Invitation, actor: uuid.UUID, *, salary: int, basis: str, start_date,
               respond_until, comment: str | None) -> HiringOffer:
    guard(db, inv, "employer")
    cur = current_offer(db, inv)
    if cur is not None and cur.status == "sent":
        raise api_error(409, "offer_open", "Оффер уже отправлен и ждёт ответа — отзовите его, чтобы отправить новый")
    if cur is not None and cur.status == "accepted":
        raise api_error(409, "offer_accepted", "Кандидат уже принял оффер — отметьте исход найма")
    ib = inv.salary_basis or "gross"
    s = convert(int(salary), basis, ib)
    if s < inv.salary_from:
        lo = convert(inv.salary_from, ib, basis) // 1000 * 1000
        raise api_error(422, "offer_below_range", f"Оффер ниже вилки приглашения: не меньше {rub(lo)} "
                                                  f"{basis_title(basis)} — «от» вилки, на которую согласился кандидат")
    if s > OFFER_MAX_UP * inv.salary_to:
        raise api_error(422, "offer_too_high", "Сумма больше трёх «до» вилки приглашения — проверьте, нет ли лишнего нуля")
    today = utcnow().astimezone(MSK).date()
    sd = _date_in(start_date, "offer_start_date")
    if sd < today or sd > today + timedelta(days=START_MAX_DAYS):
        raise api_error(422, "offer_start_date", f"Дата выхода — от сегодня до {START_MAX_DAYS} дней вперёд")
    if isinstance(respond_until, (date, str)) and not isinstance(respond_until, datetime):
        ru = datetime.combine(_date_in(respond_until, "offer_respond_until"), dtime(23, 59), MSK)
    elif isinstance(respond_until, datetime):
        ru = respond_until if respond_until.tzinfo else respond_until.replace(tzinfo=MSK)
    else:
        raise api_error(422, "offer_respond_until", "Укажите срок ответа")
    now = utcnow()
    if ru < now + timedelta(hours=1) or ru > now + timedelta(days=RESPOND_MAX_DAYS):
        raise api_error(422, "offer_respond_until", f"Срок ответа — от часа до {RESPOND_MAX_DAYS} дней")
    o = HiringOffer(invitation_id=inv.id, company_id=inv.company_id, candidate_user_id=inv.candidate_user_id,
                    created_by=actor, salary=int(salary), salary_basis=basis, start_date=sd,
                    respond_until=ru.astimezone(timezone.utc), comment=_clean(comment), status="sent", counters=[])
    db.add(o)
    _log(db, inv, "offer_sent", actor, offer_text(o))
    db.commit()
    return o


def offer_text(o: HiringOffer) -> str:
    return (f"{rub(o.salary)} {basis_title(o.salary_basis)} в месяц · выход {ddmm(o.start_date)} · "
            f"ответ до {msk(o.respond_until)}")


def _open_offer(db: Session, inv: Invitation) -> HiringOffer:
    o = current_offer(db, inv)
    if o is None or o.status != "sent":
        raise api_error(409, "offer_not_open", "Открытого оффера нет: он принят, отклонён, отозван или истёк")
    return o


def pending_counter(o: HiringOffer) -> dict | None:
    return next((c for c in o.counters or [] if c.get("status") == "pending"), None)


def _close_counter(o: HiringOffer, status: str) -> None:
    c = pending_counter(o)
    if c is not None:
        c.update(status=status, decided_at=utcnow().isoformat())
        flag_modified(o, "counters")


def withdraw_offer(db: Session, inv: Invitation, actor: uuid.UUID) -> HiringOffer:
    guard(db, inv, "employer")
    o = _open_offer(db, inv)
    _close_counter(o, "withdrawn")
    o.status = "withdrawn"
    _log(db, inv, "offer_withdrawn", actor)
    db.commit()
    return o


def accept_offer(db: Session, inv: Invitation, actor: uuid.UUID) -> HiringOffer:
    guard(db, inv, "candidate")
    o = _open_offer(db, inv)
    _close_counter(o, "withdrawn")
    o.status, o.responded_at = "accepted", utcnow()
    _log(db, inv, "offer_accepted", actor, offer_text(o))
    db.commit()
    return o


def decline_offer(db: Session, inv: Invitation, actor: uuid.UUID, reason: str | None) -> HiringOffer:
    guard(db, inv, "candidate")
    o = _open_offer(db, inv)
    _close_counter(o, "withdrawn")
    o.status, o.responded_at, o.decline_reason = "declined", utcnow(), _clean(reason)
    _log(db, inv, "offer_declined", actor, o.decline_reason)
    _set_outcome(db, inv, "declined", actor, note=o.decline_reason or "Кандидат отклонил оффер")
    db.commit()
    return o


def counter_offer(db: Session, inv: Invitation, actor: uuid.UUID, salary: int, basis: str | None,
                  comment: str | None) -> HiringOffer:
    """Встречное на оффер — те же правила, что у встречного на приглашение (app.modules.contact.service)."""
    guard(db, inv, "candidate")
    o = _open_offer(db, inv)
    if pending_counter(o) is not None:
        raise api_error(409, "counter_pending", "Встречное предложение уже отправлено — дождитесь ответа работодателя")
    if len(o.counters or []) >= COUNTER_MAX:
        raise api_error(409, "counter_limit", f"Встречных предложений на один оффер — не больше {COUNTER_MAX}")
    b = basis or o.salary_basis
    s = convert(int(salary), b, o.salary_basis)
    if s <= o.salary:
        raise api_error(422, "counter_not_higher", "Встречная сумма не выше оффера — если она вас устраивает, "
                                                   "просто примите оффер")
    if s > COUNTER_MAX_UP * o.salary:
        cap = convert(int(COUNTER_MAX_UP * o.salary), o.salary_basis, b) // 1000 * 1000
        raise api_error(422, "counter_too_far", f"Встречная сумма — не выше {rub(cap)} {basis_title(b)} "
                                                "(1,5 × оффера): иначе это уже другое предложение")
    c = {"id": secrets.token_hex(4), "salary": int(salary), "salary_basis": b, "comment": _clean(comment),
         "offer_salary": o.salary, "status": "pending", "at": utcnow().isoformat(), "decided_at": None, "note": None}
    o.counters = [*(o.counters or []), c]
    flag_modified(o, "counters")
    _log(db, inv, "offer_counter", actor, f"{rub(c['salary'])} {basis_title(b)}" + (f" · {c['comment']}"
                                                                                   if c["comment"] else ""))
    db.commit()
    return o


def decide_counter(db: Session, inv: Invitation, actor: uuid.UUID, accept: bool, note: str | None) -> HiringOffer:
    guard(db, inv, "employer")
    o = _open_offer(db, inv)
    c = pending_counter(o)
    if c is None:
        raise api_error(409, "counter_not_pending", "Нет встречного предложения, ожидающего ответа")
    c.update(status="accepted" if accept else "declined", decided_at=utcnow().isoformat(), note=_clean(note))
    flag_modified(o, "counters")
    if accept:
        was = f"{rub(o.salary)} {basis_title(o.salary_basis)}"
        o.salary, o.salary_basis = c["salary"], c["salary_basis"]
        o.status, o.responded_at = "accepted", utcnow()
        _log(db, inv, "offer_counter_accepted", actor, f"Было {was}, стало {rub(o.salary)} {basis_title(o.salary_basis)}")
        _log(db, inv, "offer_accepted", actor, "Принят на условиях встречного предложения кандидата")
    else:
        _log(db, inv, "offer_counter_declined", actor, c["note"])
    db.commit()
    return o


# ------------------------------------------------------------------ исход найма

def _set_outcome(db: Session, inv: Invitation, outcome: str, actor: uuid.UUID | None, *, note: str | None = None,
                 start_date: date | None = None) -> HiringOutcome:
    oc = HiringOutcome(invitation_id=inv.id, company_id=inv.company_id, candidate_user_id=inv.candidate_user_id,
                       outcome=outcome, start_date=start_date, note=note, decided_by=actor, created_at=utcnow())
    db.add(oc)
    for iv in interviews_of(db, inv):
        if iv.status in ACTIVE:
            iv.status = "cancelled"
    o = current_offer(db, inv)
    if o is not None and o.status == "sent":
        _close_counter(o, "withdrawn")
        o.status = "withdrawn"
    kind = {"hired": "hired", "declined": "hire_declined", "rejected": "hire_rejected"}[outcome]
    _log(db, inv, kind, actor, (f"Дата выхода {ddmm(start_date)}" if start_date else None) if outcome == "hired"
         else note)
    return oc


def set_outcome(db: Session, inv: Invitation, actor: uuid.UUID, outcome: str, note: str | None,
                start_date=None) -> HiringOutcome:
    if outcome not in OUTCOME_TITLES:
        raise api_error(422, "outcome_unknown", "Исход: вышел на работу, отказ кандидата или не прошёл")
    guard(db, inv, "employer")
    sd = None
    if outcome == "hired":
        o = current_offer(db, inv)
        if o is None or o.status != "accepted":
            raise api_error(409, "hire_needs_offer", "«Вышел на работу» — после того, как кандидат принял оффер")
        sd = _date_in(start_date, "hire_start_date") if start_date else o.start_date
    oc = _set_outcome(db, inv, outcome, actor, note=_clean(note), start_date=sd)
    db.commit()
    return oc


# ------------------------------------------------------------------ ответы API

def interview_out(iv: HiringInterview) -> dict:
    return {"id": str(iv.id), "round": iv.round, "title": iv.title, "status": iv.status, "slots": iv.slots or [],
            "chosen_slot": iv.chosen_slot, "starts_at": as_aware(iv.starts_at).isoformat() if iv.starts_at else None,
            "starts_text": msk(iv.starts_at) if iv.starts_at else None, "duration_min": iv.duration_min,
            "format": iv.format, "format_title": FORMATS.get(iv.format or "", None), "place": iv.place,
            "note": iv.note, "candidate_note": iv.candidate_note, "reschedules": iv.reschedules,
            "reschedules_left": max(0, RESCHEDULE_MAX - iv.reschedules), "result_note": iv.result_note,
            "done_at": iv.done_at.isoformat() if iv.done_at else None, "created_at": iv.created_at.isoformat()}


def offer_out(o: HiringOffer) -> dict:
    pend = pending_counter(o)
    return {"id": str(o.id), "status": o.status, "salary": o.salary, "salary_basis": o.salary_basis,
            "salary_basis_title": basis_title(o.salary_basis), "start_date": o.start_date.isoformat(),
            "respond_until": as_aware(o.respond_until).isoformat(), "respond_until_text": msk(o.respond_until),
            "comment": o.comment, "decline_reason": o.decline_reason, "counters": o.counters or [],
            "counter": pend, "counters_left": max(0, COUNTER_MAX - len(o.counters or [])),
            "created_at": o.created_at.isoformat(), "responded_at": o.responded_at.isoformat() if o.responded_at else None}


def outcome_out(oc: HiringOutcome | None) -> dict | None:
    if oc is None:
        return None
    return {"outcome": oc.outcome, "title": OUTCOME_TITLES[oc.outcome], "note": oc.note,
            "start_date": oc.start_date.isoformat() if oc.start_date else None, "at": oc.created_at.isoformat()}


def presets(db: Session, inv: Invitation) -> dict:
    """Готовые значения для форм работодателя: три слота в ближайшие рабочие дни (11:00, 15:00, 12:00 МСК),
    оффер — верх вилки приглашения, выход — понедельник через две недели, ответ — через 3 дня."""
    now = utcnow().astimezone(MSK)
    days, d = [], now.date()
    while len(days) < 3:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days.append(d)
    c = db.get(Company, inv.company_id)
    link = "https://telemost.yandex.ru/j/demo-vstrechny" if c and c.is_demo else ""
    slots = [{"starts_at": datetime.combine(day, dtime(h, 0), MSK).isoformat(), "duration_min": 60,
              "format": "video", "place": link} for day, h in zip(days, (11, 15, 12))]
    start = now.date() + timedelta(days=14)
    start += timedelta(days=(7 - start.weekday()) % 7)
    return {"slots": slots, "offer": {"salary": inv.salary_to, "salary_basis": inv.salary_basis or "gross",
                                      "start_date": start.isoformat(),
                                      "respond_until": (now.date() + timedelta(days=3)).isoformat()}}


def state_out(db: Session, inv: Invitation, side: str) -> dict:
    """Полное состояние найма по приглашению для карточки (обе стороны)."""
    ivs = interviews_of(db, inv)
    offers = offers_of(db, inv)
    if offers:
        _expire(db, offers[-1])
    oc = outcome_of(db, inv)
    stage = stage_of(db, inv)
    act = active_interview(db, inv)
    cur = offers[-1] if offers else None
    open_case = inv.status == InvitationStatus.accepted and inv.contacts_revealed_at is not None and oc is None
    out = {"invitation_id": str(inv.id), "stage": stage, "stage_title": STAGE_TITLES[stage], "open": open_case,
           "paused": inv.status == InvitationStatus.accepted and inv.contacts_revealed_at is None,
           "interview": interview_out(act) if act else None,
           "interviews": [interview_out(x) for x in reversed(ivs)],
           "offer": offer_out(cur) if cur else None, "offers": [offer_out(x) for x in reversed(offers)],
           "outcome": outcome_out(oc), "salary_from": inv.salary_from, "salary_to": inv.salary_to,
           "salary_basis": inv.salary_basis or "gross", "rules": {
               "slots_max": SLOTS_MAX, "reschedule_max": RESCHEDULE_MAX, "counter_max": COUNTER_MAX,
               "counter_max_up": COUNTER_MAX_UP, "offer_max_up": OFFER_MAX_UP, "respond_max_days": RESPOND_MAX_DAYS,
               "demo_done_anytime": _company_demo(db, inv)}}
    if side == "employer":
        out["presets"] = presets(db, inv) if open_case else None
        out["can"] = {"propose": open_case, "done": open_case and act is not None and act.status == "scheduled",
                      "cancel": open_case and act is not None,
                      "offer": open_case and (cur is None or cur.status in ("declined", "withdrawn", "expired")),
                      "withdraw_offer": open_case and cur is not None and cur.status == "sent",
                      "hired": open_case and cur is not None and cur.status == "accepted",
                      "rejected": open_case, "declined": open_case}
    else:
        out["can"] = {"choose": open_case and act is not None and act.status == "proposed",
                      "reschedule": open_case and act is not None and act.status in ("proposed", "scheduled")
                      and act.reschedules < RESCHEDULE_MAX,
                      "answer_offer": open_case and cur is not None and cur.status == "sent"}
    return out


def summary(db: Session, inv: Invitation, side: str) -> dict | None:
    """Короткая строка для списка приглашений: этап найма и «что сделать»."""
    if inv.status != InvitationStatus.accepted:
        return None
    stage = stage_of(db, inv)
    act = active_interview(db, inv)
    cur = current_offer(db, inv)
    line = STAGE_TITLES[stage]
    if act is not None and act.status == "scheduled":
        line = f"Собеседование {msk(act.starts_at)}"
    elif cur is not None and cur.status == "sent":
        line = f"Оффер {rub(cur.salary)}, ответ до {msk(cur.respond_until)}"
    return {"stage": stage, "title": STAGE_TITLES[stage], "line": line, "todo": bool(_todo_of(db, inv, side))}


def _todo_of(db: Session, inv: Invitation, side: str) -> list[str]:
    """Что ждёт действия этой стороны (счётчик у раздела «Приглашения» и плашка-напоминание)."""
    if inv.status != InvitationStatus.accepted or inv.contacts_revealed_at is None or outcome_of(db, inv):
        return []
    out = []
    act = active_interview(db, inv)
    cur = current_offer(db, inv)
    now = utcnow()
    if side == "candidate":
        if act is not None and act.status == "proposed":
            out.append("choose_slot")
        if act is not None and act.status == "scheduled" and now <= as_aware(act.starts_at) <= now + REMIND_BEFORE:
            out.append("interview_soon")
        if cur is not None and cur.status == "sent" and pending_counter(cur) is None:
            out.append("answer_offer")
    else:
        if act is not None and act.status == "reschedule":
            out.append("reschedule")
        if act is not None and act.status == "scheduled" and as_aware(act.starts_at) <= now:
            out.append("mark_done")
        if cur is not None and cur.status == "sent" and pending_counter(cur) is not None:
            out.append("counter")
    return out


def todo(db: Session, invitations: list[Invitation], side: str) -> dict:
    items = []
    for inv in invitations:
        for k in _todo_of(db, inv, side):
            act = active_interview(db, inv) if k in ("interview_soon", "mark_done", "choose_slot", "reschedule") else None
            items.append({"invitation_id": str(inv.id), "position_title": inv.position_title, "kind": k,
                          "starts_at": as_aware(act.starts_at).isoformat() if act and act.starts_at else None,
                          "starts_text": msk(act.starts_at) if act and act.starts_at else None,
                          "format_title": FORMATS.get(act.format or "") if act else None,
                          "place": act.place if act else None})
    return {"total": len(items), "items": items}


def accepted_invitations(db: Session, *, candidate_id: uuid.UUID | None = None,
                         company_id: uuid.UUID | None = None) -> list[Invitation]:
    q = select(Invitation).where(Invitation.status == InvitationStatus.accepted)
    q = q.where(Invitation.candidate_user_id == candidate_id) if candidate_id else q.where(
        Invitation.company_id == company_id)
    return list(db.scalars(q.order_by(Invitation.created_at.desc())).all())


def count_hired(db: Session, company_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(HiringOutcome).where(HiringOutcome.company_id == company_id,
                                                                           HiringOutcome.outcome == "hired")) or 0


def cabinet_note(db: Session, user_id, kind: str, key: str, title: str, body: str, url: str) -> None:
    """Запись в «Уведомления» кабинета (app.modules.subs, И25): то же, что ушло в push и письмо. Отправку делает найм
    сам (channels=[]), лента только показывает. Сбой не ломает шаг найма."""
    try:
        from app.modules.subs.delivery import add_notification

        add_notification(db, user_id, kind, key[:160], title, body, url, channels=[])
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logging.getLogger(__name__).exception("hiring: cabinet notification failed")
