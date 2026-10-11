"""Две попытки теста рядом (И26): кандидату — в истории попыток, работодателю — в карточке кандидата.

Сравниваются две завершённые сессии одного направления: оценка уровня θ ± погрешность, точность (SE), доля верных,
грейд и статус после попытки, время, число оценённых заданий и сколько семейств и вариантов заданий повторилось.
«Что изменилось и почему» — правилами, без LLM; числа в текстах — через app.core.fmt (тот же формат, что в
интерфейсе: десятичная запятая, «−»).

Повторы считаются только по новым оценённым заданиям попытки: контрольные (канареечные) задания кандидату и
работодателю не раскрываются (Р27), у дотестирования (mode=confirm) перенесённые ответы прошлой попытки — не новые
задания. Банк выдаёт повтор из другого субпула и с 09.10 исключает семейства всех прошлых попыток по направлению
(exposure.choose_subpool, service.seen_families, exposure.AppCATSession: запасной путь — давно виденные, LRU, с новым
вариантом); заглушка (engine=stub, только в тестах и без банка) выдаёт один и тот же набор — повтор 100 %.

Хранение — в test_sessions.result, без миграции.
"""
from __future__ import annotations

from datetime import datetime
import math
import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import as_aware, get_db, utcnow
from app.core.deps import require_role
from app.core.enums import TestSessionStatus, UserRole
from app.core.errors import api_error, err
from app.core.fmt import ru_num, theta_se
from app.modules.assessment.models import TestSession
from app.modules.auth.models import User
from app.modules.catalog.seed_data import DIRECTION_TITLES, GRADES
from app.modules.catalog.ext import DirectionId

Z95 = 1.96
STATUS_TITLES = {"confirmed": "подтверждён", "accepted_lower": "принят уровень ниже", "provisional": "предварительно",
                 "unconfirmed": "не подтверждён"}
MODE_TITLES = {"full": "полный тест", "express": "экспресс-тест", "confirm": "дотестирование",
               "refine": "уточнение уровня"}
Direction = DirectionId


# ------------------------------------------------------------------ одна попытка

def _items(ts: TestSession) -> tuple[str, list[str], list[str], int]:
    """(движок, семейства, варианты, перенесено из прошлой попытки) — только новые оценённые неканареечные задания."""
    st = (ts.result or {}).get("state") or {}
    if "items" in st:  # банк заданий
        new = [i for i in st.get("items") or [] if i.get("done") and not i.get("canary")]
        prior = [i for i in st.get("prior") or [] if i.get("done") and not i.get("canary")]
        fams = sorted({str(i.get("family_id")) for i in new})
        vars_ = sorted({str(i.get("variant_id") or f"{i.get('family_id')}:{i.get('seed')}") for i in new})
        return "bank", fams, vars_, len(prior)
    answered = (st.get("answers") or {}).keys()
    ids = sorted(i for i in st.get("item_ids") or [] if i in answered)  # заглушка: задание = семейство = вариант
    return "stub", ids, ids, 0


def _status(er: dict, out: dict) -> str:
    if out.get("accepted_lower"):
        return "accepted_lower"
    if er.get("confirmed"):
        return "confirmed"
    if er.get("provisional"):
        return "provisional"
    return "unconfirmed"


def _time_s(ts: TestSession, det: dict) -> float | None:
    t = det.get("time_used_s")
    if t is not None:
        return float(t)
    if ts.started_at and ts.finished_at:
        return round((as_aware(ts.finished_at) - as_aware(ts.started_at)).total_seconds(), 1)
    return None


def attempt_view(ts: TestSession) -> dict:
    """Попытка для экрана сравнения. Поля families/variants — внутренние (для подсчёта повторов), наружу не уходят."""
    from app.modules.assessment.service import _mode

    r = ts.result or {}
    er = r.get("engine_result") or {}
    det = er.get("details") or {}
    out = r.get("outcome") or {}
    engine, fams, vars_, prior = _items(ts)
    theta = ts.theta if ts.theta is not None else er.get("theta")
    se = ts.theta_se if ts.theta_se is not None else er.get("se")
    answered, correct = er.get("answered"), er.get("correct")
    status = _status(er, out)
    grade_after = out.get("accepted_lower") or (ts.claimed_grade_id if status in ("confirmed", "provisional") else None)
    ext = det.get("extension") or None
    return {
        "id": str(ts.id), "direction": ts.direction_id, "direction_title": DIRECTION_TITLES.get(ts.direction_id),
        "mode": _mode(ts), "mode_title": MODE_TITLES.get(_mode(ts), _mode(ts)),
        "claimed_grade": ts.claimed_grade_id, "claimed_grade_title": GRADES.get(ts.claimed_grade_id),
        "started_at": as_aware(ts.started_at).isoformat() if ts.started_at else None,
        "finished_at": as_aware(ts.finished_at).isoformat() if ts.finished_at else None,
        "time_used_s": _time_s(ts, det),
        "theta": theta, "se": se, "theta_text": theta_se(theta, se) if theta is not None else None,
        "correct": correct, "answered": answered,
        "accuracy": (round(float(correct) / answered, 4) if answered else None),
        "n_items": len(vars_), "prior_items": prior,
        "status": status, "status_title": STATUS_TITLES[status],
        "grade_after": grade_after, "grade_after_title": GRADES.get(grade_after) if grade_after else None,
        # грейд направления после попытки (как применено правилами: повторное подтверждение, правило 90 дней и т. п.)
        "category_grade": out.get("grade"), "message": out.get("message"),
        "is_sandbox": bool(ts.is_sandbox), "engine": engine, "subpool": det.get("subpool"),
        "extension_items": (ext or {}).get("items") if isinstance(ext, dict) else None,
        "stop_reason": det.get("stop_reason"),
        # повтор семейства запасным путём LRU (И26, 09.10): новых семейств направления в банке не осталось
        "lru_repeats": sum(1 for i in (((r.get("state") or {}).get("items")) or [])
                           if i.get("repeat") and i.get("done") and not i.get("canary")),
        "families": fams, "variants": vars_,
    }


PUBLIC_DROP = ("families", "variants")


def public(view: dict, audience: str = "candidate") -> dict:
    out = {k: v for k, v in view.items() if k not in PUBLIC_DROP}
    if audience == "employer":
        out.pop("id", None)  # работодателю — без идентификаторов сессий кандидата
        out.pop("message", None)
    return out


# ------------------------------------------------------------------ сравнение

def _min(s: float | None) -> str:
    if s is None:
        return "—"
    m = s / 60
    if m >= 10:
        return f"{math.floor(m + 0.5)} мин"  # округление «половина вверх», как в интерфейсе
    return f"{ru_num(math.floor(m * 10 + 0.5) / 10, 1)} мин"


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{round(100 * x)} %"


def overlap(a: dict, b: dict) -> dict:
    """Сколько семейств и вариантов второй попытки было в первой (доля — от заданий второй попытки)."""
    fa, fb = set(a["families"]), set(b["families"])
    va, vb = set(a["variants"]), set(b["variants"])
    rf, rv = len(fa & fb), len(va & vb)
    return {"repeated_families": rf, "n_families_second": len(fb),
            "share_families": round(rf / len(fb), 4) if fb else None,
            "repeated_variants": rv, "n_variants_second": len(vb),
            "share_variants": round(rv / len(vb), 4) if vb else None,
            "same_subpool": (a.get("subpool") is not None and a.get("subpool") == b.get("subpool")),
            "engine": b["engine"]}


def compare(a: dict, b: dict, audience: str = "candidate") -> dict:
    """a — более ранняя попытка, b — более поздняя (виды из attempt_view)."""
    if a["direction"] != b["direction"]:
        raise api_error(422, "different_directions", "Сравниваются попытки одного направления")
    ov = overlap(a, b)
    d_theta = se_diff = z = None
    within = None
    if a["theta"] is not None and b["theta"] is not None:
        d_theta = round(float(b["theta"]) - float(a["theta"]), 4)
        if a["se"] is not None and b["se"] is not None:
            se_diff = round(math.sqrt(float(a["se"]) ** 2 + float(b["se"]) ** 2), 4)
            z = round(d_theta / se_diff, 3) if se_diff > 0 else None
            within = abs(d_theta) <= Z95 * se_diff
    delta = {
        "theta": d_theta, "se_diff": se_diff, "z": z, "within_error": within,
        "interval": round(Z95 * se_diff, 4) if se_diff is not None else None,
        "se": (round(float(b["se"]) - float(a["se"]), 4) if a["se"] is not None and b["se"] is not None else None),
        "accuracy": (round(b["accuracy"] - a["accuracy"], 4)
                     if a["accuracy"] is not None and b["accuracy"] is not None else None),
        "time_s": (round(b["time_used_s"] - a["time_used_s"], 1)
                   if a["time_used_s"] is not None and b["time_used_s"] is not None else None),
        "n_items": b["n_items"] - a["n_items"],
        "grade_changed": a["grade_after"] != b["grade_after"],
        "status_changed": a["status"] != b["status"],
    }
    return {"first": public(a, audience), "second": public(b, audience), "overlap": ov, "delta": delta,
            "changes": changes(a, b, ov, delta)}


def changes(a: dict, b: dict, ov: dict, d: dict) -> list[dict]:
    """«Что изменилось и почему» — правилами. Каждый пункт: {id, title, text}."""
    out: list[dict] = []

    def add(id_: str, title: str, text: str) -> None:
        out.append({"id": id_, "title": title, "text": text})

    if d["theta"] is not None:
        txt = f"{a['theta_text']} → {b['theta_text']}, разница {ru_num(d['theta'], sign=True)}."
        if d["within_error"] is not None:
            band = ru_num(d["interval"])
            if d["within_error"]:
                txt += (f" Это в пределах погрешности разности (±{band} при 95 %): по двум попыткам уровень один и "
                        f"тот же, разница — обычный разброс измерения.")
            else:
                txt += (f" Разница больше погрешности разности (±{band} при 95 %): уровень "
                        f"{'выше' if d['theta'] > 0 else 'ниже'}, это не случайный разброс.")
        add("theta", "Оценка уровня θ", txt)
    if d["se"] is not None:
        if abs(d["se"]) < 0.02:
            why = "точность почти та же"
        else:
            why = "точность выше" if d["se"] < 0 else "точность ниже"
        reasons = []
        if d["n_items"]:
            reasons.append(f"оценённых заданий {a['n_items'] + a['prior_items']} → {b['n_items'] + b['prior_items']}")
        if b.get("extension_items"):
            reasons.append(f"у порога грейда добавлено {b['extension_items']} задания")
        if a["mode"] != b["mode"]:
            reasons.append(f"режимы разные: {a['mode_title']} и {b['mode_title']}")
        add("se", "Погрешность (SE)",
            f"{ru_num(a['se'])} → {ru_num(b['se'])} — {why}" + (f": {'; '.join(reasons)}." if reasons else ".")
            + " Тест останавливается, когда погрешность достаточно мала для решения по грейду.")
    if d["accuracy"] is not None:
        add("accuracy", "Доля верных ответов",
            f"{_pct(a['accuracy'])} → {_pct(b['accuracy'])} ({a['correct']} из {a['answered']} и "
            f"{b['correct']} из {b['answered']}). Тест адаптивный: после верных ответов задания труднее, поэтому "
            f"сравнивают θ, а не долю верных.")
    if d["status_changed"] or d["grade_changed"]:
        ga = a["grade_after_title"] or "—"
        gb = b["grade_after_title"] or "—"
        add("status", "Грейд и статус",
            f"{a['claimed_grade_title']}: {a['status_title']} ({ga}) → {b['claimed_grade_title']}: {b['status_title']} "
            f"({gb}). Решение по грейду — по вероятности уровня не ниже порога (подтверждение — от 80 %), "
            f"поэтому при близком к порогу θ статус может смениться и при разнице в пределах погрешности.")
    else:
        add("status", "Грейд и статус",
            f"Без изменений: {b['claimed_grade_title']} — {b['status_title']}"
            + (f" ({b['grade_after_title']})." if b["grade_after_title"] else "."))
    if a["claimed_grade"] != b["claimed_grade"]:
        add("claimed", "Заявленный грейд",
            f"{a['claimed_grade_title']} → {b['claimed_grade_title']}: стартовая трудность и порог решения разные; "
            f"θ — на общей шкале, его можно сравнивать.")
    if d["time_s"] is not None:
        add("time", "Время", f"{_min(a['time_used_s'])} → {_min(b['time_used_s'])}.")
    rf, nf = ov["repeated_families"], ov["n_families_second"]
    if ov["engine"] == "stub":
        txt = (f"Тестовая заглушка выдаёт один и тот же набор заданий: повторилось {rf} из {nf}. "
               f"В банке заданий повтор идёт из другого субпула, семейства прошлых попыток исключены.")
    elif rf == 0:
        txt = (f"Повторов нет: 0 семейств из {nf}, все варианты (тексты и числа) новые. Повтор выдаётся из "
               f"{'того же' if ov['same_subpool'] else 'другого'} субпула банка (параллельная форма), "
               f"семейства прошлых попыток в повтор не попадают.")
    else:
        why = ("новые семейства направления в банке кончились — повторяются те, что вы видели давнее всего"
               if b.get("lru_repeats") else
               "попытки до 09.10: субпулов два, попытка через одну возвращалась в субпул первой, а исключались "
               "семейства только прошлой попытки" if ov["same_subpool"] else
               "дотестирование у порога в более ранней попытке брало задания второго субпула")
        txt = (f"Повторилось семейств: {rf} из {nf} ({_pct(ov['share_families'])}), вариантов — "
               f"{ov['repeated_variants']} из {ov['n_variants_second']}: {why}. В повторённом семействе "
               f"генерируется новый вариант (другие числа и код).")
    if b["mode"] in ("confirm", "refine"):
        txt += (f" {'Дотестирование' if b['mode'] == 'confirm' else 'Уточнение уровня'}: {b['prior_items']} ответов "
                "прошлой попытки перенесены, повторы считаются по новым.")
    add("overlap", "Задания", txt)
    if a["mode"] != b["mode"] and "express" in (a["mode"], b["mode"]):
        add("mode", "Режим", "Экспресс-тест короче и его погрешность шире — сравнение с полным тестом условное.")
    if a["is_sandbox"] or b["is_sandbox"]:
        add("sandbox", "Демо-режим",
            "Попытки в демо-режиме жюри: правило 30/90 дней не действует; у обычных кандидатов — как обычно.")
    return out


# ------------------------------------------------------------------ выборка

def finished_attempts(db: Session, user_id: uuid.UUID, direction: str) -> list[TestSession]:
    rows = db.scalars(select(TestSession).where(
        TestSession.user_id == user_id, TestSession.direction_id == direction,
        TestSession.status == TestSessionStatus.finished).order_by(TestSession.finished_at, TestSession.created_at)).all()
    return [t for t in rows if (t.result or {}).get("engine_result")]


def pair(rows: list[TestSession], a_id: uuid.UUID | None = None, b_id: uuid.UUID | None = None):
    if a_id is None and b_id is None:
        return (rows[-2], rows[-1]) if len(rows) >= 2 else None
    by = {t.id: t for t in rows}
    if a_id not in by or b_id not in by:
        return None
    a, b = by[a_id], by[b_id]
    if a.id == b.id:
        raise api_error(422, "same_attempt", "Выберите две разные попытки")
    key = lambda t: (as_aware(t.finished_at) or datetime.min, t.created_at)  # noqa: E731
    return (a, b) if key(a) <= key(b) else (b, a)


def _direction(db: Session, user_id: uuid.UUID, direction: str | None) -> str | None:
    if direction:
        return direction
    from app.modules.profiles.models import CandidateSpecialization

    d = db.scalar(select(CandidateSpecialization.direction_id).where(
        CandidateSpecialization.user_id == user_id, CandidateSpecialization.is_primary.is_(True)))
    if d:
        return d
    last = db.scalar(select(TestSession.direction_id).where(TestSession.user_id == user_id,
                                                            TestSession.status == TestSessionStatus.finished)
                     .order_by(TestSession.finished_at.desc()).limit(1))
    return last


def _list_item(v: dict, audience: str) -> dict:
    keep = ("id", "mode", "mode_title", "claimed_grade", "claimed_grade_title", "finished_at", "theta", "se",
            "theta_text", "status", "status_title", "grade_after", "grade_after_title", "is_sandbox", "n_items")
    out = {k: v[k] for k in keep}
    if audience == "employer":
        out.pop("id")
    return out


def for_candidate(db: Session, user_id: uuid.UUID, direction: str | None = None,
                  a_id: uuid.UUID | None = None, b_id: uuid.UUID | None = None) -> dict:
    from app.modules.assessment import service
    from app.modules.assessment.rules import check_can_start
    from app.modules.profiles.models import CandidateProfile
    from app.modules.profiles.specializations import ensure_specialization

    if (a_id is None) != (b_id is None):
        raise api_error(422, "pair_required", "Укажите обе попытки (a и b) или ни одной")
    for sid in (a_id, b_id):
        if sid is not None:
            ts = service.get_own_session(db, user_id, sid)  # чужая или несуществующая — 404
            if ts.status != TestSessionStatus.finished:
                raise api_error(409, "test_not_finished", "Попытка ещё не завершена")
            direction = direction or ts.direction_id
    direction = _direction(db, user_id, direction)
    profile = db.get(CandidateProfile, user_id)
    sandbox = service.is_sandbox(profile) if profile is not None else False
    rows = finished_attempts(db, user_id, direction) if direction else []
    if a_id is not None:
        a, b = db.get(TestSession, a_id), db.get(TestSession, b_id)
        if a.direction_id != b.direction_id:
            raise api_error(422, "different_directions", "Сравниваются попытки одного направления")
    p = pair(rows, a_id, b_id)
    views = [attempt_view(t) for t in rows]
    cmp = compare(attempt_view(p[0]), attempt_view(p[1])) if p else None
    retake_grade = rows[-1].claimed_grade_id if rows else None
    can, reason = False, None
    if retake_grade and profile is not None:
        now = utcnow()
        st = get_settings()
        spec = ensure_specialization(db, profile, direction)
        failed = ({} if sandbox else service.recent_failed(db, user_id, direction, now, st.retake_same_grade_days))
        chk = check_can_start(spec.grade_id, spec.locked_until, retake_grade, now, sandbox, failed,
                              st.retake_same_grade_days)
        can, reason = chk.allowed, (None if chk.allowed else chk.message)
    return {"direction": direction, "direction_title": DIRECTION_TITLES.get(direction) if direction else None,
            "attempts": [_list_item(v, "candidate") for v in views], "comparison": cmp,
            "sandbox": sandbox, "retake_grade": retake_grade, "can_retake_now": can, "retake_reason": reason,
            "note": ("В демо-режиме жюри вторую попытку можно пройти сразу — правило 30/90 дней не действует; "
                     "у обычных кандидатов правила как обычно." if sandbox else None)}


def for_employer(db: Session, user_id: uuid.UUID, privacy: dict, direction: str | None = None) -> dict:
    if not privacy.get("show_attempts", True):
        return {"available": False, "reason": "hidden_by_candidate",
                "text": "Кандидат скрыл сравнение попыток теста"}
    direction = _direction(db, user_id, direction)
    rows = finished_attempts(db, user_id, direction) if direction else []
    if len(rows) < 2:
        return {"available": False, "reason": "single_attempt", "direction": direction, "n_attempts": len(rows),
                "text": "Попытка теста одна — сравнивать не с чем"}
    p = pair(rows)
    return {"available": True, "direction": direction, "direction_title": DIRECTION_TITLES.get(direction),
            "n_attempts": len(rows), "attempts": [_list_item(attempt_view(t), "employer") for t in rows],
            "comparison": compare(attempt_view(p[0]), attempt_view(p[1]), audience="employer")}


# ------------------------------------------------------------------ API работодателя
# (кандидатский эндпоинт — в assessment/router.py: GET /api/assessment/attempts)

employer_router = APIRouter(prefix="/api/employer", tags=["employer"])
_employer = require_role(UserRole.employer)


@employer_router.get(
    "/candidates/{ref}/attempts", summary="Две попытки теста кандидата рядом (если попыток ≥ 2 и кандидат не скрыл)",
    responses={401: err("Не выполнен вход"), 403: err("Только для работодателя"),
               404: err("Кандидат не найден или скрыл профиль"),
               409: err("company_required — сначала заполните профиль компании")})
def employer_attempts(ref: str, direction: Direction | None = None, user: User = Depends(_employer),
                      db: Session = Depends(get_db)) -> dict:
    from app.modules.invitations.service import profile_by_ref
    from app.modules.matching.router import my_company
    from app.modules.profiles.facts import DEFAULT_PRIVACY

    my_company(db, user)
    p = profile_by_ref(db, ref)
    return for_employer(db, p.user_id, {**DEFAULT_PRIVACY, **(p.privacy or {})}, direction)
