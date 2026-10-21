"""«Один в один» на открытом генераторе Dev_dev (MIT): выгрузка мира в JSON — запускать В ИХ окружении.

Повторяет их ``app.evaluation.matching_eval.run(seed, 40, 1000)`` шаг в шаг (тот же ``random.Random(seed)``, тот же
порядок вызовов): популяция → профили через их тест (``confirmed_level``) → вакансии → их три выдачи (IT Match, по
резюме, случайный) с их метриками. Ничего в их коде не меняется; единственная обёртка — над их ``evaluate``: она
вызывает оригинал и дополнительно запоминает счёт «верно / всего» по навыкам заданий (чистая функция тех же ответов —
ГСЧ не трогает), чтобы передать нашему продукту подтверждённые навыки с числами, а не выдуманные.

После их трёх выдач сохраняется состояние ГСЧ: наш ранжировщик (rank_ours.py) продолжает тот же поток для разбивки
равных баллов, как четвёртая выдача в их же ``_evaluate``.

В JSON два раздела: ``observed`` — то, что видит система (профиль кандидата и вакансия, как их IT Match), и ``truth`` —
скрытая истина и метки их ``_relevance`` (наш ранжировщик читает только ``observed``; ``truth`` — для метрик).

Запуск (их репозиторий, коммит фиксируется в выгрузке):
  cd <их_repo>/backend && python <путь>/export_world.py --seed 2026 --out /tmp/dd_2026.json
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

import app.evaluation.matching_eval as me  # noqa: E402
import app.evaluation.testing as tst  # noqa: E402
from app.services.specializations import GRADE_ORDER  # noqa: E402

_SKILLS: dict[int, dict[str, list[int]]] = {}
_CALLS: list[list[tuple]] = []  # все тесты по порядку: [(уровень задания, вид, верно, навыки)]
_orig_evaluate = tst.evaluate


def _evaluate(items, responses, target):
    out = _orig_evaluate(items, responses, target)
    per: dict[str, list[int]] = {}
    call = []
    for item, r in zip(items, responses, strict=True):
        ok = int(_is_correct(item, r))
        call.append((item.level, item.kind, bool(ok), tuple(item.skills)))
        for s in item.skills:
            per.setdefault(s, [0, 0])
            per[s][0] += ok
            per[s][1] += 1
    _SKILLS[id(out)] = per
    _CALLS.append(call)
    return out


def _pooled(calls: list[list[tuple]]) -> dict | None:
    """Все ответы кандидата за его путь по тестам — одной оценкой их же функцией estimate (наш продукт оценивает θ
    по всем ответам теста, а не по последнему уровню)."""
    from app.services.assessment.engine import estimate

    marks = [(lv, kind, ok) for c in calls for (lv, kind, ok, _s) in c]
    if not marks:
        return None
    theta, error = estimate(marks)
    per: dict[str, list[int]] = {}
    for c in calls:
        for (_lv, _k, ok, skills) in c:
            for s in skills:
                per.setdefault(s, [0, 0])
                per[s][0] += int(ok)
                per[s][1] += 1
    return {"theta": round(theta, 2), "error": round(error, 2), "correct": sum(m[2] for m in marks),
            "total": len(marks), "n_tests": len(calls), "skill_counts": per}


def _is_correct(item, r):
    from app.services.assessment.engine import is_correct

    return is_correct(item, r)


tst.evaluate = _evaluate


def _evaluate_per(scorer, jobs, population, profiles, rng):
    """Их _evaluate строка в строку (тот же порядок вызовов ГСЧ) + метрики по каждой вакансии — для парного сравнения.
    Совпадение итогов с их _evaluate проверено: на тех же зёрнах средние равны их отчёту до последнего знака."""
    import statistics

    p5, p10, ndcg, overrated, mrr = [], [], [], [], []
    for opening, vacancy in jobs:
        ranked = sorted(zip(population, profiles, strict=True),
                        key=lambda pair: (scorer(opening, vacancy, *pair), rng.random()), reverse=True)
        gains = [me._relevance(opening, person) for person, _ in ranked]
        p5.append(sum(g == 2 for g in gains[:5]) / 5)
        p10.append(sum(g == 2 for g in gains[:me.K]) / me.K)
        ndcg.append(me._ndcg(gains))
        target = GRADE_ORDER.index(opening.grade)
        overrated.append(sum(GRADE_ORDER.index(p.true_grade) < target for p, _ in ranked[:me.K]) / me.K)
        mrr.append(next((1 / r for r, g in enumerate(gains, 1) if g == 2), 0.0))
    score = me.SystemScore(statistics.fmean(p5), statistics.fmean(p10), statistics.fmean(ndcg), statistics.fmean(overrated))
    per = [{"p5": a, "p10": b, "ndcg10": c, "overrated10": d, "rr": e} for a, b, c, d, e in zip(p5, p10, ndcg, overrated, mrr)]
    return score, per


def _grade(g) -> str | None:
    return None if g is None else (g.value if hasattr(g, "value") else str(g))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--vacancies", type=int, default=40)
    ap.add_argument("--candidates", type=int, default=1000)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    # --- их run() шаг в шаг; исход теста каждого кандидата ловим обёрткой их confirmed_level (ГСЧ не трогает)
    rng = random.Random(a.seed)
    population = me.people(rng, a.candidates)
    _SKILLS.clear()
    captured: list[tuple] = []
    orig_cl = tst.confirmed_level

    def _cl(person, r):
        start = len(_CALLS)
        res = orig_cl(person, r)
        captured.append((*res, _pooled(_CALLS[start:])))
        return res

    me.confirmed_level = _cl
    profiles = [me._candidate(person, rng) for person in population]
    me.confirmed_level = orig_cl
    jobs = [(o, me._vacancy(o)) for o in me.openings(rng, a.vacancies)]
    systems = {
        "IT Match": me._it_match,
        "По резюме (заявленное)": lambda opening, _v, person, _c: (me._resume_score(opening, person),),
        "Случайный порядок": lambda *_: (rng.random(),),
    }
    theirs, theirs_per = {}, {}
    for name, scorer in systems.items():
        s, per_v = _evaluate_per(scorer, jobs, population, profiles, rng)
        theirs[name] = {"p5": s.precision_at_5, "p10": s.precision_at_10, "ndcg10": s.ndcg_at_10,
                        "overrated10": s.overrated_in_top}
        theirs_per[name] = per_v
    state = rng.getstate()

    cands = []
    for i, (person, prof, (level, outcome, pooled)) in enumerate(zip(population, profiles, captured, strict=True)):
        p = prof.profile
        cands.append({
            "id": f"c{i:04d}",
            "specialization": p.specialization.value,
            "claimed_grade": _grade(p.grade),
            "confirmed_grade": _grade(p.confirmed_grade),
            "test": None if outcome is None else {
                "level": level, "theta": outcome.theta, "error": outcome.error, "correct": outcome.correct,
                "total": outcome.total, "passed": outcome.passed, "confident": outcome.confident,
                "score": outcome.score, "skills": list(outcome.skills),
                "skill_counts": _SKILLS.get(id(outcome), {}),
            },
            "pooled": pooled,
            "declared_skills": [s.slug for s in p.skills],
            "fsp_tier": prof.categories[0].tier if prof.categories else None,
            "city": p.city,
            "work_format": p.work_formats[0].value if p.work_formats else None,
            "salary_min": p.salary_min,
        })
    vacs = [{"id": f"v{j:02d}", "specialization": o.specialization.value, "grade": _grade(o.grade),
             "skills": list(o.skills), "city": o.city, "work_format": o.work_format.value,
             "salary_min": v.salary_min, "salary_max": v.salary_max} for j, (o, v) in enumerate(jobs)]
    rel = [[me._relevance(o, person) for person in population] for o, _ in jobs]
    true_grade_idx = [GRADE_ORDER.index(person.true_grade) for person in population]
    vac_grade_idx = [GRADE_ORDER.index(o.grade) for o, _ in jobs]
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        commit = "unknown"
    doc = {
        "what": "мир генератора Dev_dev (MIT) для сравнения «один в один»",
        "their_commit": commit, "seed": a.seed, "vacancies": a.vacancies, "candidates": a.candidates,
        "their_metrics": theirs,
        "their_per_vacancy": theirs_per,
        "rng_state_after_their_systems": [state[0], list(state[1]), state[2]],
        "observed": {"candidates": cands, "vacancies": vacs},
        "truth": {"relevance": rel, "true_grade_idx": true_grade_idx, "vacancy_grade_idx": vac_grade_idx,
                  "grade_order": [_grade(g) for g in GRADE_ORDER]},
    }
    Path(a.out).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"seed": a.seed, "commit": commit, "their": theirs}, ensure_ascii=False))


if __name__ == "__main__":
    main()
