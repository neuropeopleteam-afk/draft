"""Сводки проверки с живыми пользователями: публичная (для /validation) и служебная (для команды).

Публичная сводка — только суммарные цифры и только при N ≥ MIN_N ответивших; срез по роли — при N роли ≥ MIN_N.
Репетиции (is_test) и отозвавшие согласие в цифры не входят. Имён, почт, кодов и построчных ответов здесь нет.
Служебная — построчно по меткам «К-01», «Р-03», без имён; комментарии — по запросу, уже очищенные от контактов.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import as_aware, utcnow
from app.modules.study import path as P
from app.modules.study import stats, texts
from app.modules.study.models import StudyAnswer, StudyParticipant

MSK = ZoneInfo("Europe/Moscow")
ROLE_PL = {"candidate": "кандидаты", "employer": "работодатели"}


@dataclass
class Row:
    p: StudyParticipant
    d: dict
    ans: StudyAnswer | None
    status: str

    @property
    def sus(self) -> float | None:
        return stats.sus_score(self.ans.sus) if self.ans and len(self.ans.sus or []) == 10 else None

    @property
    def p5(self) -> float | None:
        return stats.p_at_k([r["rating"] for r in (self.ans.ratings or [])], texts.REL_THRESHOLD) if self.ans else None

    @property
    def path_s(self) -> float | None:
        if not self.d["path_done"] or not self.p.started_at:
            return None
        return max(0.0, (self.d["done_at"] - as_aware(self.p.started_at)).total_seconds())


def rows(db: Session, *, include_test: bool = False, include_unstarted: bool = False) -> list[Row]:
    now = utcnow()
    q = select(StudyParticipant).where(StudyParticipant.withdrawn_at.is_(None)).order_by(StudyParticipant.created_at,
                                                                                       StudyParticipant.label)
    if not include_test:
        q = q.where(StudyParticipant.is_test.is_(False))
    answers = {a.participant_id: a for a in db.scalars(select(StudyAnswer))}
    out = []
    for p in db.scalars(q):
        if p.started_at is None and not include_unstarted:
            continue
        d = P.derive(db, p)
        a = answers.get(p.id)
        out.append(Row(p, d, a, P.status_of(p, d, a is not None, now)))
    return out


def _ms(v: float | None, d: int = 0) -> float | None:
    return None if v is None else round(v, d)


def _fmt_date(dt: datetime) -> str:
    return as_aware(dt).astimezone(MSK).strftime("%d.%m.%Y")


def _step_times(r: Row) -> dict[str, float]:
    """Секунды на каждый шаг (от предыдущего шага или согласия); пропущенная регистрация не считается."""
    prev = as_aware(r.p.started_at)
    out: dict[str, float] = {}
    for k in r.d["keys"]:
        s = r.d["steps"][k]
        if s["at"] is None:
            break
        if not s["skipped"]:
            out[k] = max(0.0, (s["at"] - prev).total_seconds())
        prev = s["at"] if not s["skipped"] else prev
    return out


def _sus_block(rs: list[Row]) -> dict:
    vals = [r.sus for r in rs if r.sus is not None]
    m = stats.mean_ci(vals, lo=0, hi=100)
    ge = sum(1 for v in vals if v >= stats.SUS_BENCHMARK)
    return {**m, "median": stats.median(vals), "min": min(vals) if vals else None, "max": max(vals) if vals else None,
            "ge_benchmark": stats.share(ge, len(vals)), "benchmark": stats.SUS_BENCHMARK}


def _completion(rs: list[Row]) -> dict:
    done = sum(1 for r in rs if r.status == "done")
    stopped = [r for r in rs if r.status == "stopped"]
    resolved = done + len(stopped)
    where: dict[str, int] = {}
    for r in stopped:
        where[r.d["current"] or "-"] = where.get(r.d["current"] or "-", 0) + 1
    return {"started": len(rs), "done": done, "stopped": len(stopped), "active": sum(1 for r in rs if r.status == "active"),
            "share": stats.share(done, resolved), "stopped_at": where}


def _time_block(rs: list[Row]) -> dict:
    t = [r.path_s for r in rs if r.path_s is not None]
    steps: dict[str, list[float]] = {}
    for r in rs:
        if r.status == "done":
            for k, v in _step_times(r).items():
                steps.setdefault(k, []).append(v)
    return {"n": len(t), "median_s": stats.median(t), "iqr_s": stats.quartiles(t),
            "step_median_s": {k: stats.median(v) for k, v in steps.items()}}


def _p5_block(rs: list[Row]) -> dict:
    vals = [(r.p5, r) for r in rs if r.ans and r.ans.ratings]
    per = [v for v, _ in vals]
    ratings = [x["rating"] for _, r in vals for x in r.ans.ratings]
    by_rank: dict[int, list[int]] = {}
    for _, r in vals:
        for x in r.ans.ratings:
            by_rank.setdefault(int(x["rank"]), []).append(x["rating"])
    n = len(per)
    out = {"n": n, "threshold": texts.REL_THRESHOLD, "k": 5}
    if n < stats.MIN_N:
        return out  # мелкие группы не раскрываем
    ge4 = sum(1 for x in ratings if x >= texts.REL_THRESHOLD)
    ge3 = sum(1 for x in ratings if x >= 3)
    out.update({"mean": sum(per) / n, "ci": stats.boot_mean_ci(per), "ratings": len(ratings), "ratings_relevant": ge4,
                "ratings_ge3": ge3, "mean_rating": sum(ratings) / len(ratings),
                "by_rank": [{"rank": k, "mean": sum(v) / len(v), "n": len(v)} for k, v in sorted(by_rank.items())],
                "dist": {str(i): sum(1 for x in ratings if x == i) for i in range(1, 6)},
                "algorithms": sorted({(r.ans.selection or {}).get("algorithm") for _, r in vals if (r.ans.selection or {}).get("algorithm")})})
    return out


def _belief_block(rs: list[Row]) -> dict:
    vals = [r.ans.belief for r in rs if r.ans and r.ans.belief is not None]
    if len(vals) < stats.MIN_N:
        return {"n": len(vals)}
    return {**stats.mean_ci([float(v) for v in vals], lo=1, hi=5), "dist": {str(i): vals.count(i) for i in range(1, 6)},
            "agree": stats.share(sum(1 for v in vals if v >= 4), len(vals))}


def _fit_block(rs: list[Row]) -> dict:
    vals = [r.ans.grade_fit for r in rs if r.ans and r.ans.grade_fit]
    if len(vals) < stats.MIN_N:
        return {"n": len(vals)}
    return {"n": len(vals), **{k: vals.count(k) for k in texts.GRADE_FIT}}


def _errors_block(rs: list[Row]) -> dict:
    with_err = [r for r in rs if r.d["errors"]]
    server = [r for r in rs if any((e.status or 0) >= 500 or e.status == 0 for e in r.d["errors"])]
    by_code: dict[str, int] = {}
    for r in rs:
        for e in r.d["errors"]:
            c = e.code or f"http_{e.status}"
            by_code[c] = by_code.get(c, 0) + 1
    return {"participants": len(with_err), "of": len(rs), "server": len(server), "total": sum(len(r.d["errors"]) for r in rs),
            "by_code": dict(sorted(by_code.items(), key=lambda kv: -kv[1])[:8])}


def public_summary(db: Session) -> dict:
    rs = rows(db)
    ans = [r for r in rs if r.ans]
    if len(ans) < stats.MIN_N:
        return {"shown": False, "min_n": stats.MIN_N}
    roles = {ro: [r for r in rs if r.p.role == ro] for ro in texts.ROLES}
    roles_ans = {ro: [r for r in v if r.ans] for ro, v in roles.items()}
    invited = db.scalars(select(StudyParticipant).where(StudyParticipant.is_test.is_(False),
                                                         StudyParticipant.withdrawn_at.is_(None))).all()
    invited_n = sum(1 for p in invited if p.is_active or p.started_at)
    first = min(as_aware(r.p.started_at) for r in ans)
    last = max(as_aware(r.ans.submitted_at) for r in ans)
    n_by = {ro: len(v) for ro, v in roles_ans.items()}
    src_n = {s: sum(1 for r in ans if r.p.source == s) for s in texts.SOURCES}
    src = ("участники " + texts.SOURCES[next(s for s, k in src_n.items() if k)] if sum(1 for k in src_n.values() if k) == 1
           else "участники приглашены командой: " + "; ".join(f"{texts.SOURCES[s].replace('приглашены командой ', '')} — {k}"
                                                           for s, k in src_n.items() if k))
    sig = (f"Люди, {src}. N = {len(ans)} ответивших ("
           + ", ".join(f"{ROLE_PL[ro]} — {n_by[ro]}" for ro in texts.ROLES) + "), "
           + (_fmt_date(first) if _fmt_date(first) == _fmt_date(last) else f"{_fmt_date(first)} – {_fmt_date(last)}")
           + ". Репетиции команды не учитываются.")
    ok = lambda ro: len(roles_ans[ro]) >= stats.MIN_N  # noqa: E731 — срез по роли — только при N роли ≥ MIN_N
    tags: dict[str, int] = {}
    for r in ans:
        for t in r.ans.tags or []:
            tags[t] = tags.get(t, 0) + 1
    comp = _completion(rs)
    return {
        "shown": True, "min_n": stats.MIN_N, "signature": sig,
        "sources": {s: k for s, k in src_n.items() if k},
        "world": ("Люди оценивали платформу на демонстрационных данных: кандидаты в подборке — смоделированные профили, "
                  "а не реальные люди."
                  + (" Кандидаты проходили экспресс-тест (5–7 заданий), а не полный."
                     if any(r.p.mode == "quick" and r.p.role == "candidate" for r in ans) else "")),
        "period": {"from": first.isoformat(), "to": last.isoformat()},
        "n": {"invited": invited_n, "started": len(rs), "done": comp["done"], "answered": len(ans),
              "by_role": {ro: {"started": len(roles[ro]), "answered": n_by[ro],
                               "done": sum(1 for r in roles[ro] if r.status == "done")} for ro in texts.ROLES}},
        "sus": {**_sus_block(ans), "by_role": {ro: _sus_block(roles_ans[ro]) for ro in texts.ROLES if ok(ro)}},
        "completion": {**comp, "by_role": {ro: _completion(roles[ro]) for ro in texts.ROLES if ok(ro)}},
        "time": {**_time_block(rs), "by_role": {ro: _time_block(roles[ro]) for ro in texts.ROLES if ok(ro)}},
        "p5": _p5_block(roles_ans["employer"]),
        "belief": {ro: _belief_block(roles_ans[ro]) for ro in texts.ROLES},
        "grade_fit": _fit_block(roles_ans["candidate"]),
        "errors": _errors_block(rs),
        "blockers": {texts.BLOCKER_TAGS[k]: v for k, v in sorted(tags.items(), key=lambda kv: -kv[1])},
        "step_titles": {ro: {k: t for k, t, _ in texts.PATH[ro]} for ro in texts.ROLES},
        "scale": {"rel": list(texts.REL_SCALE), "sus_benchmark": stats.SUS_BENCHMARK},
    }


def admin_report(db: Session, *, with_texts: bool = False) -> dict:
    rs = rows(db, include_test=True, include_unstarted=True)
    items = []
    for r in rs:
        a = r.ans
        items.append({
            "label": r.p.label, "role": r.p.role, "batch": r.p.batch, "mode": r.p.mode, "source": r.p.source, "test": r.p.is_test,
            "status": r.status if r.p.started_at else ("closed" if not r.p.is_active else "not_started"),
            "started_at": r.p.started_at.isoformat() if r.p.started_at else None,
            "steps": {k: ({"at": s["at"].isoformat(), "skipped": s["skipped"]} if s["at"] else None)
                      for k, s in r.d["steps"].items()},
            "step_seconds": {k: _ms(v) for k, v in _step_times(r).items()},
            "current": r.d["current"], "path_seconds": _ms(r.path_s),
            "errors": [{"key": e.key, "status": e.status, "code": e.code} for e in r.d["errors"]],
            "last_screen": r.d["views"][-1].key if r.d["views"] else None,
            "screens": len(r.d["views"]),
            "answers": ({"sus": _ms(r.sus, 1), "p5": r.p5, "ratings": a.ratings, "belief": a.belief, "grade_fit": a.grade_fit,
                         "tags": a.tags, "path_done": a.path_done, "submitted_at": a.submitted_at.isoformat(),
                         **({"comment": a.comment} if with_texts else {"has_comment": bool(a.comment)})} if a else None),
        })
    return {"generated_at": utcnow().isoformat(), "participants": items,
            "public": public_summary(db)}
