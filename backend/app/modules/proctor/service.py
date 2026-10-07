"""Камера во время теста по согласию: согласие, режим камеры в сессии, приём событий, итог в достоверности.

Принципы (152-ФЗ): анализ кадра — только в браузере кандидата (MediaPipe Face Detector, файлы модели с нашего
домена); изображения на сервер не уходят; лицо не сравнивается с эталоном и не распознаётся — это не
биометрическая идентификация, а подсчёт «есть ли в кадре лицо и сколько их». На сервер — только события.
Без камеры тест проходит полностью; работодатель видит нейтральную пометку «тест без камеры».
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.db import as_aware, utcnow
from app.core.enums import ConsentKind, TestSessionStatus
from app.core.errors import api_error
from app.core.legal import OPERATOR
from app.modules.assessment.models import TestSession
from app.modules.auth.models import Consent, User
from app.modules.proctor import rules
from app.modules.proctor.models import ProctorEvent, ProctorSession

log = logging.getLogger("app.proctor")

CONSENT_VERSION = "2026-10-07"
MAX_EVENTS_PER_SESSION = 2000
MAX_OBSERVED_MS_SLACK = 120_000  # наблюдение по заданию не больше времени задания по часам сервера + запас

CONSENT = {
    "title": "Согласие на анализ видео с камеры во время теста",
    "what": [
        "Во время теста браузер раз в 0,7 секунды проверяет кадр с вашей камеры: есть ли в нём лицо, не больше ли "
        "одного лица, не закрыта ли камера и передаёт ли она изображение.",
        "Проверка идёт только на вашем устройстве. Видео и снимки никуда не отправляются и не записываются.",
        "Лицо не сравнивается с фотографией и не распознаётся — система не знает, кто перед камерой. Это не "
        "биометрическая идентификация.",
    ],
    "stored": [
        "Только события по заданиям: «нет лица в кадре 12 с на задании 4», «в кадре два лица», «камера закрыта», "
        "а также сколько секунд камера наблюдала каждое задание.",
        "Кадры, признаки лица и звук не хранятся и не передаются.",
    ],
    "how_long": "Столько же, сколько хранится сама попытка теста: события удаляются вместе с ней и с учётной записью.",
    "who_sees": [
        "Вы — индикатор камеры во время теста и все свои события после него.",
        "Работодатель — только итог рядом с достоверностью результата: «камера: включена, замечаний нет» или "
        "«есть замечания: …». События по заданиям ему не показываются.",
        "Аналитики ФСП — только обезличенные агрегаты по платформе.",
    ],
    "effect": "Камера не меняет оценку уровня и грейд. Замечания только снижают «достоверность результата», как уход "
              "со вкладки. Без камеры тест проходит полностью, работодатель видит нейтральную пометку «тест без камеры».",
    "revoke": "Согласие можно отозвать в настройках кабинета: камера в текущем тесте выключится, дальше он пойдёт без "
              "камеры. Перед каждым тестом выбор — с камерой или без — делается заново.",
}


def consent_text() -> dict:
    o = OPERATOR
    return {"kind": ConsentKind.proctoring.value, "version": CONSENT_VERSION, **CONSENT,
            "operator": f"{o['full_name']} ({o['short_name']}), ИНН {o['inn']}, адрес для обращений: {o['email']}"}


# ------------------------------------------------------------------ согласие

def active_consent(db: Session, user_id: uuid.UUID) -> Consent | None:
    return db.scalar(select(Consent).where(Consent.user_id == user_id, Consent.kind == ConsentKind.proctoring,
                                           Consent.revoked_at.is_(None)).order_by(Consent.granted_at.desc()).limit(1))


def grant(db: Session, user: User) -> Consent:
    c = active_consent(db, user.id)
    if c is not None and c.document_version != CONSENT_VERSION:  # новая редакция текста — новая запись согласия
        c.revoked_at = utcnow()
        c = None
    if c is None:
        c = Consent(user_id=user.id, kind=ConsentKind.proctoring, document_version=CONSENT_VERSION)
        db.add(c)
        db.flush()
    return c


def revoke(db: Session, user: User) -> int:
    """Отзыв: согласие закрыто; в незавершённых тестах камера выключается с текущего задания."""
    c = active_consent(db, user.id)
    if c is not None:
        c.revoked_at = utcnow()
    stopped = 0
    rows = db.scalars(select(ProctorSession).join(TestSession, TestSession.id == ProctorSession.session_id).where(
        ProctorSession.user_id == user.id, ProctorSession.mode == "camera",
        TestSession.status == TestSessionStatus.in_progress)).all()
    for ps in rows:
        ts = db.get(TestSession, ps.session_id)
        if _close_window(ps, rules.current_position((ts.result or {}).get("state") or {}), "revoked"):
            stopped += 1
    return stopped


def consent_state(db: Session, user: User) -> dict:
    c = active_consent(db, user.id)
    return {"active": c is not None, "granted_at": as_aware(c.granted_at).isoformat() if c else None,
            "version": c.document_version if c else None, "current_version": CONSENT_VERSION,
            "text": consent_text()}


# ------------------------------------------------------------------ режим камеры в сессии

def own_session(db: Session, user: User, session_id: uuid.UUID, *, active: bool = False) -> TestSession:
    ts = db.get(TestSession, session_id)
    if ts is None or ts.user_id != user.id:
        raise api_error(404, "session_not_found", "Сессия теста не найдена")
    if active and ts.status != TestSessionStatus.in_progress:
        raise api_error(409, "session_closed", "Сессия теста уже завершена")
    return ts


def _proctor(db: Session, ts: TestSession, lock: bool = False) -> ProctorSession | None:
    q = select(ProctorSession).where(ProctorSession.session_id == ts.id)
    return db.scalar(q.with_for_update() if lock else q)


def _state(ts: TestSession) -> dict:
    return (ts.result or {}).get("state") or {}


def _close_window(ps: ProctorSession, position: int, reason: str) -> bool:
    ws = [dict(w) for w in ps.windows or []]
    if not ws or ws[-1].get("to") is not None:
        return False
    ws[-1]["to"] = max(int(ws[-1].get("from") or 1), position)
    ps.windows, ps.stop_reason = ws, reason
    flag_modified(ps, "windows")
    return True


def start(db: Session, user: User, ts: TestSession, mode: str, reason: str | None, client: dict | None) -> dict:
    """Кандидат выбрал режим: camera (нужно действующее согласие) или без камеры (declined/unsupported/denied).

    Повторный вызов: camera → camera — камера включена снова после перезагрузки страницы; без камеры → camera —
    камера включена посреди теста (наблюдение с текущего задания); camera → без камеры — как выключение кнопкой.
    """
    if mode not in rules.MODES:
        raise api_error(422, "bad_mode", "Неизвестный режим камеры")
    consent = active_consent(db, user.id) if mode == "camera" else None
    if mode == "camera" and consent is None:
        raise api_error(409, "consent_required", "Нет согласия на анализ видео с камеры — включите камеру на экране "
                                                 "перед тестом")
    ps = _proctor(db, ts, lock=True)
    st = _state(ts)
    pos = rules.current_position(st)
    started = any(i.get("time_s") is not None for i in rules.items_from_state(st)) or pos > 1
    clean_client = {k: str(v)[:40] for k, v in (client or {}).items() if k in ("model", "fps", "backend", "build")}
    if ps is None:
        ps = ProctorSession(session_id=ts.id, user_id=user.id, mode=mode, reason=(reason or None) and reason[:120],
                            client=clean_client, windows=[], observed={})
        db.add(ps)
    if mode == "camera":
        ws = [dict(w) for w in ps.windows or []]
        if ws and ws[-1].get("to") is None:
            ps.resumes += 1  # окно наблюдения открыто: страницу перезагрузили, камера включена снова
        else:
            ws.append({"from": pos, "to": None, "mid": bool(started)})
            ps.stop_reason = None
        ps.windows = ws
        ps.mode, ps.consent_id, ps.consent_version = "camera", consent.id, consent.document_version
        ps.client = clean_client or ps.client
        flag_modified(ps, "windows")
    elif ps.mode == "camera":
        _close_window(ps, pos, "user")
    else:
        ps.mode, ps.reason = mode, (reason or None) and reason[:120]
    db.commit()
    return session_view(db, ts, ps)


def stop(db: Session, user: User, ts: TestSession, reason: str) -> dict:
    ps = _proctor(db, ts, lock=True)
    if ps is not None and ps.mode == "camera":
        _close_window(ps, rules.current_position(_state(ts)), reason if reason in ("user", "error") else "user")
        db.commit()
    return session_view(db, ts, ps)


def record(db: Session, user: User, ts: TestSession, events: list[dict], observed: list[dict]) -> dict:
    """Приём пачки событий из браузера. Значения ограничиваются; события вне окна наблюдения не учитываются."""
    ps = _proctor(db, ts, lock=True)
    if ps is None or ps.mode != "camera":
        raise api_error(409, "camera_not_enabled", "Камера в этом тесте не включена")
    if not ps.windows or ps.windows[-1].get("to") is not None:
        raise api_error(409, "camera_stopped", "Камера в этом тесте выключена")
    if active_consent(db, user.id) is None:
        _close_window(ps, rules.current_position(_state(ts)), "revoked")
        db.commit()
        raise api_error(409, "consent_revoked", "Согласие на анализ видео отозвано — камера выключена")
    items = {i["token"]: i for i in rules.items_from_state(_state(ts)) if i.get("token")}
    now = utcnow()
    accepted = 0
    for e in events:
        it = items.get(e.get("item_id"))
        if it is None or e.get("kind") not in rules.KINDS:
            continue
        if ps.events_count >= MAX_EVENTS_PER_SESSION:
            ps.events_dropped += 1
            continue
        at = None
        try:
            at = datetime.fromtimestamp(int(e.get("at_ms")) / 1000, UTC) if e.get("at_ms") else None
        except (TypeError, ValueError, OverflowError, OSError):
            at = None
        if at is not None and not (as_aware(ts.started_at) - timedelta(minutes=5) <= at <= now + timedelta(minutes=5)):
            at = None  # часы браузера — справочно; явно неверное время не сохраняем
        faces = e.get("faces")
        db.add(ProctorEvent(proctor_id=ps.id, position=it["position"], kind=e["kind"],
                            duration_ms=max(0, min(int(e.get("duration_ms") or 0), rules.MAX_EVENT_MS)),
                            faces=max(0, min(int(faces), 20)) if isinstance(faces, int) else None, started_at=at))
        ps.events_count += 1
        accepted += 1
    obs = dict(ps.observed or {})
    for o in observed:
        it = items.get(o.get("item_id"))
        if it is None:
            continue
        key = str(it["position"])
        cur = dict(obs.get(key) or {"ms": 0, "frames": 0, "face": 0})
        limit = int((float(it["time_s"]) * 1000 if it.get("time_s") is not None
                     else (now - as_aware(ts.started_at)).total_seconds() * 1000) + MAX_OBSERVED_MS_SLACK)
        for k, cap in (("ms", limit), ("frames", 100_000), ("face", 100_000)):
            cur[k] = max(0, min(int(cur.get(k) or 0) + max(0, int(o.get(k) or 0)), cap))
        obs[key] = cur
    ps.observed = obs
    flag_modified(ps, "observed")
    db.commit()
    return {"accepted": accepted, "events_total": ps.events_count, "dropped": ps.events_dropped}


# ------------------------------------------------------------------ итог

def _events(db: Session, ps: ProctorSession) -> list[ProctorEvent]:
    return list(db.scalars(select(ProctorEvent).where(ProctorEvent.proctor_id == ps.id)
                           .order_by(ProctorEvent.position, ProctorEvent.created_at)).all())


def summarize(db: Session, ts: TestSession, ps: ProctorSession | None) -> dict:
    if ps is None:
        return rules.aggregate(None, [], [])
    stop_ = None
    if ps.windows and ps.windows[-1].get("to") is not None:
        stop_ = {"position": ps.windows[-1]["to"], "reason": ps.stop_reason}
    evs = [{"position": e.position, "kind": e.kind, "duration_ms": e.duration_ms, "faces": e.faces}
           for e in _events(db, ps)]
    return rules.aggregate(ps.mode, rules.items_from_state(_state(ts)), evs, ps.observed, ps.windows, stop_)


def apply_to_result(db: Session, ts: TestSession, details: dict) -> None:
    """Хук завершения теста (assessment.service.finish_session): итог камеры — в достоверность результата.

    Ошибка здесь не должна мешать завершению теста: при сбое итог камеры просто не добавляется.
    """
    try:
        from app.modules.assessment import integrity

        ps = _proctor(db, ts)
        summ = summarize(db, ts, ps)
        view = rules.employer_view(summ)
        details["camera"] = view
        if details.get("integrity") is not None:
            details["integrity"] = integrity.add_reasons(details["integrity"], summ["reasons"], camera=view)
        if ps is not None:
            ps.summary = {k: summ[k] for k in ("mode", "camera", "title", "points", "remarks", "notes", "totals")}
            ps.finished_at = utcnow()
    except Exception:  # noqa: BLE001
        log.exception("proctor: не удалось добавить итог камеры в результат сессии %s", ts.id)


def session_view(db: Session, ts: TestSession, ps: ProctorSession | None = None, *, events: bool = False) -> dict:
    """Для кандидата: режим, окна наблюдения, итог (как у работодателя) и — по запросу — свои события."""
    ps = ps if ps is not None else _proctor(db, ts)
    summ = summarize(db, ts, ps)
    out = {
        "session_id": str(ts.id), "status": ts.status.value, "mode": ps.mode if ps else None,
        "camera_active": bool(ps and ps.mode == "camera" and ps.windows and ps.windows[-1].get("to") is None),
        "windows": ps.windows if ps else [], "resumes": ps.resumes if ps else 0,
        "consent_version": ps.consent_version if ps else None,
        "summary": {**rules.employer_view(summ), "points": summ["points"], "totals": summ["totals"]},
    }
    if events and ps is not None:
        out["events"] = [{"position": e.position, "kind": e.kind, "title": rules.KIND_TITLES.get(e.kind, e.kind),
                          "duration_s": round(e.duration_ms / 1000, 1), "faces": e.faces,
                          "counted": e.duration_ms >= rules.MIN_MS.get(e.kind, 0),
                          "at": as_aware(e.started_at).isoformat() if e.started_at else None} for e in _events(db, ps)]
        out["items"] = [{"position": p["position"], "observed_s": round(p["observed_ms"] / 1000, 1),
                         "time_s": p["time_s"], "no_face_s": round(p["no_face"] / 1000, 1),
                         "multi_face_s": round(p["multi_face"] / 1000, 1),
                         "off_s": round((p["blocked"] + p["camera_off"] + p["uncovered_ms"]) / 1000, 1)}
                        for p in summ["per_item"]]
    return out


def my_sessions(db: Session, user: User, limit: int = 10) -> list[dict]:
    rows = db.execute(select(TestSession, ProctorSession).outerjoin(
        ProctorSession, ProctorSession.session_id == TestSession.id).where(TestSession.user_id == user.id)
        .order_by(TestSession.created_at.desc()).limit(limit)).all()
    out = []
    for ts, ps in rows:
        summ = summarize(db, ts, ps)
        out.append({"session_id": str(ts.id), "direction": ts.direction_id, "claimed_grade": ts.claimed_grade_id,
                    "status": ts.status.value, "started_at": as_aware(ts.started_at).isoformat() if ts.started_at else None,
                    "mode": ps.mode if ps else None, "events": ps.events_count if ps else 0,
                    "summary": rules.employer_view(summ)})
    return out


# ------------------------------------------------------------------ демо жюри

def seed_demo(db: Session, ts: TestSession, camera: bool) -> None:
    """Демо-сессия жюри (jury/seed.py) перед finish_session: с камерой — согласие, окно наблюдения с первого
    задания и наблюдение по каждому заданию без единого события («замечаний нет»); без камеры — выбор кандидата."""
    user = db.get(User, ts.user_id)
    if not camera:
        db.add(ProctorSession(session_id=ts.id, user_id=ts.user_id, mode="declined", client={}, windows=[], observed={}))
        db.flush()
        return
    consent = grant(db, user)
    observed = {str(i["position"]): {"ms": int(float(i["time_s"]) * 1000), "frames": int(float(i["time_s"]) / 0.7),
                                     "face": int(float(i["time_s"]) / 0.7)}
                for i in rules.items_from_state(_state(ts)) if i.get("time_s") is not None}
    db.add(ProctorSession(session_id=ts.id, user_id=ts.user_id, mode="camera", consent_id=consent.id,
                          consent_version=consent.document_version,
                          client={"model": "blaze_face_short_range", "fps": "1.4", "backend": "cpu"},
                          windows=[{"from": 1, "to": None, "mid": False}], observed=observed))
    db.flush()


# ------------------------------------------------------------------ агрегат для ФСП

K_MIN = 5  # как в Кабинете ФСП: группы меньше 5 не показываются


def stats(db: Session, days: int | None = None) -> dict:
    since = utcnow() - timedelta(days=days) if days else None
    q = select(TestSession.id).where(TestSession.status == TestSessionStatus.finished)
    if since is not None:
        q = q.where(TestSession.finished_at >= since)
    finished = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    pq = select(ProctorSession).join(TestSession, TestSession.id == ProctorSession.session_id).where(
        TestSession.status == TestSessionStatus.finished)
    if since is not None:
        pq = pq.where(TestSession.finished_at >= since)
    rows = db.scalars(pq).all()
    modes = {m: 0 for m in rules.MODES}
    with_remarks, kinds = 0, {"no_face": 0, "multi_face": 0, "off": 0}
    observed = []
    for ps in rows:
        modes[ps.mode] = modes.get(ps.mode, 0) + 1
        s = ps.summary or {}
        if ps.mode == "camera" and s.get("remarks"):
            with_remarks += 1
            t = s.get("totals") or {}
            kinds["no_face"] += int(bool(t.get("no_face_items")))
            kinds["multi_face"] += int(bool(t.get("multi_face_items")))
            kinds["off"] += int(bool(t.get("off_items")))
        if ps.mode == "camera" and (s.get("totals") or {}).get("observed_s") is not None:
            observed.append(float(s["totals"]["observed_s"]))
    hide = (lambda v: v if v >= K_MIN or v == 0 else None)
    camera = modes.get("camera", 0)
    return {
        "period_days": days, "k_min": K_MIN, "tests_finished": finished,
        "modes": {m: hide(v) for m, v in modes.items()},
        "without_record": hide(max(0, finished - len(rows))),
        "camera_share": round(camera / finished, 3) if finished and camera >= K_MIN else None,
        "camera_with_remarks": hide(with_remarks),
        "camera_remarks_share": round(with_remarks / camera, 3) if camera >= K_MIN else None,
        "remark_kinds": {k: hide(v) for k, v in kinds.items()},
        "observed_min_median": round(sorted(observed)[len(observed) // 2] / 60, 1) if len(observed) >= K_MIN else None,
        "note": "Обезличенные агрегаты по завершённым тестам; группы меньше 5 скрыты. Кадры и события по заданиям "
                "в Кабинет ФСП не попадают.",
    }
