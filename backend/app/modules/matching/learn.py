"""«Учитывать решения компании» — ограниченная объяснимая подстройка весов подбора (learn-v1, 21.10.2026).

По умолчанию ВЫКЛЮЧЕНО: работодатель включает галочкой в фильтрах подборки (``learn_from_company``); выключил — веса
сразу прежние (ничего не хранится, веса каждый раз считаются заново из решений — это и есть откат).

Сигналы компании (по всем её потребностям): «подходит» в подборке и отправленное приглашение — плюс, «не подходит» —
минус. Для каждого решения берутся компоненты балла кандидата из той версии подборки, где решение принято (те же,
что видит HR: тест, обязательный стек, желательный стек, ФСП, короткие задания; все — 0..1, подтверждённые данные).

Правило: Δ_k = среднее компонента k у «плюсов» − у «минусов»; множитель m_k = 1 + clip(Δ_k · n/(n+20), −0,3, +0,3),
где n — число решений (чем их меньше, тем осторожнее); новые веса w_k·m_k нормируются к сумме 1. Нужно не меньше
3 «плюсов» и 3 «минусов», иначе — «мало решений», веса прежние. Меняется только балл внутри яруса: статус грейда,
ярус обязательных навыков, фильтры и правило «грейд — только по тесту» не трогаются; самоописание (T0) в балл не
входит и подстройкой не возвращается.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

VERSION = "learn-v1"
MAX_SHIFT = 0.3
PRIOR_N = 20
MIN_EACH = 3
KEYS = ("test", "stack_required", "stack_desired", "fsp", "probe")
TITLES = {"test": "результат теста", "stack_required": "подтверждённый обязательный стек",
          "stack_desired": "подтверждённый желательный стек", "fsp": "достижения ФСП", "probe": "короткие задания"}


def _components(db: Session, company_id: uuid.UUID) -> tuple[list[dict], list[dict], dict]:
    from app.modules.invitations.models import Invitation, InvitationStatus
    from app.modules.matching.models import EmployerNeed, SelectionVersion
    from app.modules.mutual.models import SelectionFeedback
    from app.modules.profiles.models import CandidateProfile

    needs = {n.id for n in db.scalars(select(EmployerNeed).where(EmployerNeed.company_id == company_id))}
    if not needs:
        return [], [], {"fit": 0, "unfit": 0, "invited": 0}
    versions = db.scalars(select(SelectionVersion).where(SelectionVersion.need_id.in_(needs))
                          .order_by(SelectionVersion.version)).all()
    by_v: dict[tuple, dict] = {}
    latest: dict[tuple, dict] = {}
    for v in versions:
        for r in v.results or []:
            c = r.get("components") or {}
            if not c:
                continue
            by_v[(v.need_id, v.version, r.get("ref"))] = c
            latest[(v.need_id, r.get("ref"))] = c
    pos: dict[tuple, dict] = {}
    neg: dict[tuple, dict] = {}
    cnt = {"fit": 0, "unfit": 0, "invited": 0}
    for f in db.scalars(select(SelectionFeedback).where(SelectionFeedback.need_id.in_(needs))):
        c = by_v.get((f.need_id, f.version, f.candidate_ref)) or latest.get((f.need_id, f.candidate_ref))
        if not c:
            continue
        (pos if f.verdict == "fit" else neg)[(f.need_id, f.candidate_ref)] = c
        cnt["fit" if f.verdict == "fit" else "unfit"] += 1
    invs = db.scalars(select(Invitation).where(Invitation.company_id == company_id,
                                               Invitation.need_id.is_not(None),
                                               Invitation.status != InvitationStatus.withdrawn)).all()
    refs = {p.user_id: p.public_ref for p in db.scalars(select(CandidateProfile).where(
        CandidateProfile.user_id.in_({i.candidate_user_id for i in invs})))} if invs else {}
    for i in invs:
        ref = refs.get(i.candidate_user_id)
        c = latest.get((i.need_id, ref))
        if c and (i.need_id, ref) not in neg:
            pos[(i.need_id, ref)] = c
            cnt["invited"] += 1
    return list(pos.values()), list(neg.values()), cnt


def _mean(rows: list[dict], k: str) -> float:
    return sum(float(r.get(k) or 0.0) for r in rows) / len(rows) if rows else 0.0


def adjust(base: dict, pos: list[dict], neg: list[dict]) -> dict:
    """Чистая функция правила (тестируется отдельно): {status, after, shift_pp, delta, n}."""
    n = len(pos) + len(neg)
    if len(pos) < MIN_EACH or len(neg) < MIN_EACH:
        return {"status": "few", "after": dict(base), "shift_pp": {k: 0.0 for k in KEYS}, "delta": {}, "n": n}
    trust = n / (n + PRIOR_N)
    delta = {k: round(_mean(pos, k) - _mean(neg, k), 3) for k in KEYS}
    mult = {k: 1 + max(-MAX_SHIFT, min(MAX_SHIFT, delta[k] * trust)) for k in KEYS}
    raw = {k: base[k] * mult[k] for k in KEYS}
    s = sum(raw.values()) or 1.0
    total = sum(base[k] for k in KEYS)
    after = {k: round(raw[k] / s * total, 4) for k in KEYS}
    return {"status": "ok", "after": after, "delta": delta, "n": n, "trust": round(trust, 3),
            "shift_pp": {k: round((after[k] - base[k]) * 100, 1) for k in KEYS},
            "means": {"fit": {k: round(_mean(pos, k), 3) for k in KEYS},
                      "unfit": {k: round(_mean(neg, k), 3) for k in KEYS}}}


def _pct(x: float) -> str:
    return f"{round(x * 100):d} %"


def company_weights(db: Session, company_id: uuid.UUID, base: dict) -> dict:
    """Подстроенные веса для компании + объяснение для HR (meta.learning)."""
    pos, neg, cnt = _components(db, company_id)
    r = adjust(base, pos, neg)
    out = {"version": VERSION, "on": True, "status": r["status"], "decisions": {**cnt, "plus": len(pos),
                                                                               "minus": len(neg)},
           "weights_before": dict(base), "weights_after": r["after"], "shift_pp": r["shift_pp"],
           "rule": f"Δ = среднее компонента у «подходит»/приглашённых − у «не подходит»; сдвиг веса до ±"
                   f"{int(MAX_SHIFT * 100)} % с доверием n/(n+{PRIOR_N}); нужно ≥ {MIN_EACH} решений каждого вида."}
    if r["status"] != "ok":
        out["text"] = (f"Мало решений для подстройки: «подходит»/приглашено — {len(pos)}, «не подходит» — {len(neg)} "
                       f"(нужно не меньше {MIN_EACH} каждого). Веса прежние.")
        return out
    out["means"] = r["means"]
    top = sorted(KEYS, key=lambda k: -abs(r["shift_pp"][k]))[:2]
    parts = []
    for k in top:
        if abs(r["shift_pp"][k]) < 0.5:
            continue
        parts.append(f"вес «{TITLES[k]}» {_pct(base[k])} → {_pct(r['after'][k])} (у одобренных "
                     f"{str(r['means']['fit'][k]).replace('.', ',')}, у отклонённых "
                     f"{str(r['means']['unfit'][k]).replace('.', ',')})")
    out["text"] = ("По решениям компании (" + f"{len(pos)} одобрено, {len(neg)} отклонено): "
                   + ("; ".join(parts) if parts else "заметной разницы нет, веса почти прежние") + ".")
    return out
