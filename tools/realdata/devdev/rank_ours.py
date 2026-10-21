"""«Один в один» на генераторе Dev_dev: наш продукт (подбор match-v2) — четвёртой выдачей в их же процедуре оценки.

Вход — выгрузка export_world.py (их мир, их тест, их метки). Наш ранжировщик читает ТОЛЬКО ``observed`` — то же, что
получает их IT Match: вакансию (направление, грейд, стек) и профиль кандидата (подтверждённый тестом грейд и исход
теста, заявленные навыки и грейд, уровень ФСП). Метки ``truth`` — только для метрик.

Переводчик (адаптер) их полей в наш формат — правила зафиксированы заранее, в протоколе (DEVDEV_PROTOCOL.md):
* направление: backend → backend, frontend → frontend, mobile → mobile, data → data_ml, devops → devops, qa → qa,
  security → security (mobile/devops — направления расширения каталога, видимы при CATALOG_EXT_ENABLED);
* грейд: intern/junior/middle/senior/lead → наши с тем же именем (lead — при GRADES_EXT_ENABLED; без него — senior);
* результат теста: их шкала уровней 1..5 с порогом грейда k − 0,5 → наша шкала порогов (junior −1, middle 0,
  senior 1, lead 2): θ_наш = θ_их − 2,5, SE без изменения (шаг между порогами в обеих шкалах = 1);
  кандидат, не сдавший ни одного уровня, — ярус «грейд не подтверждён» (направление — из анкеты);
* навыки: счёт «верно / всего» по навыкам заданий их теста → подтверждённые тестом навыки (T1) с этим счётом;
  заявленные в профиле навыки → самоописание (T0, в балл не входит); теги — нашим словарём (find_stack) по
  названию навыка; навык, которого наш словарь не знает, отбрасывается (так же поступил бы продукт);
* ФСП: их «подтверждено ФСП» с уровнем elite / advanced / base → достижение, подтверждённое ФСП: всероссийское 1 место /
  всероссийское 3 место / региональное участие (10 место), дисциплина «алгоритмическое программирование»;
* вакансия → текст потребности «{Грейд} {направление}. Стек: a, b, c.» + направление и грейд полями формы
  (как «Принесите свой набор»); город, формат и зарплата не передаются: их IT Match порядок по ним не меняет
  (docstring их scorer.for_need), а их метка от них не зависит.
Порядок — функции бенчмарка продукта: пул подборки bench2.pool_for (как build_selection: категория по тесту,
ярус «не подтверждён» ниже, добор ступенью выше) и порядок ranking.order_bundles (match-v2, каскад стека).
Кандидаты вне пула идут после пула в случайном порядке — равные ключи разбиваются тем же ГСЧ их _evaluate,
продолженным с состояния после их трёх выдач. Метрики — их формулы (P@5, P@10 по метке 2; nDCG@10 с выгодой
2^g − 1 и идеалом по всей популяции; переоценённые в топ-10) + MRR по метке 2 (у них нет; справочно).

  python3 tools/realdata/devdev/rank_ours.py --world /tmp/dd_1.json [--config final|base] [--out res.json]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONFIGS = {
    # конфигурация финального стенда (ответ «Победы» 21.10): match-v2 + расширение каталога + Lead/Principal
    "final": {"MATCH_V2": "1", "CATALOG_EXT_ENABLED": "true", "GRADES_EXT_ENABLED": "true"},
    # базовый каталог без расширения (справочно)
    "base": {"MATCH_V2": "1", "CATALOG_EXT_ENABLED": "false", "GRADES_EXT_ENABLED": "false"},
}
DIR_MAP = {"backend": "backend", "frontend": "frontend", "mobile": "mobile", "data": "data_ml", "devops": "devops",
           "qa": "qa", "security": "security"}
DIR_TITLE = {"backend": "бэкенд-разработчик", "frontend": "фронтенд-разработчик", "mobile": "мобильный разработчик",
             "data_ml": "специалист по данным и машинному обучению", "devops": "DevOps-инженер",
             "qa": "инженер по тестированию", "security": "специалист по информационной безопасности"}
GRADE_TITLE = {"intern": "Стажёр", "junior": "Junior", "middle": "Middle", "senior": "Senior", "lead": "Lead"}
# название навыка их справочника, как его написал бы работодатель
SKILL_PHRASE = {"machine-learning": "машинное обучение", "data-analysis": "анализ данных",
                "qa-automation": "автоматизация тестирования", "information-security": "информационная безопасность",
                "ci-cd": "CI/CD", "reverse-engineering": "reverse engineering", "go": "Go"}
# режим подборки — выбор работодателя в фильтрах: default — как есть; grade_exact — «строго запрошенный грейд»
MODES = {"default": {}, "grade_exact": {"grade_exact": True}}
MODE = "default"
THETA_SHIFT = 2.5
THETA_SOURCE = "last"  # last — исход теста подтверждённого уровня (то же, что видит их IT Match); pooled — все ответы
# пути по тестам одной оценкой их estimate (справочно, на зёрнах разработки ниже)
FSP_MAP = {"elite": ("national", 1), "advanced": ("national", 3), "base": ("regional", 10)}
K = 10


def setup(config: str) -> None:
    for k, v in CONFIGS[config].items():
        os.environ[k] = v
    os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/devdev_rank.db")
    os.environ.setdefault("LLM_DISABLED", "true")
    sys.path.insert(0, str(ROOT / "backend"))
    sys.path.insert(0, str(ROOT / "tools" / "realdata"))


def our_tag(slug: str) -> str | None:
    from app.modules.catalog.dictionary import find_stack

    found = find_stack(SKILL_PHRASE.get(slug, slug))
    return min(found, key=found.get) if found else None


def our_dir(spec: str) -> str | None:
    from app.modules.catalog import ext
    from app.modules.catalog.seed_data import DIRECTIONS

    d = DIR_MAP.get(spec)
    if d in DIRECTIONS or (d in ext.EXT_DIRECTIONS and d in ext.visible_ext()):
        return d
    return None


def our_grade(g: str | None) -> str | None:
    from app.modules.catalog.seed_data import GRADES

    if g is None:
        return None
    return g if g in GRADES else "senior"


def to_bundle(c: dict):
    """Наблюдаемый профиль их кандидата → наш Bundle через продуктовый путь загрузки набора (bench_upload._to_bundle)."""
    from app.modules.matching.bench_upload import _to_bundle

    d = our_dir(c["specialization"])
    if d is None:
        return None  # направления нет в нашем каталоге: у кандидата нет нашего теста и категории — вне подборки
    t = c.get("pooled") if THETA_SOURCE == "pooled" else c.get("test")
    confirmed = c.get("confirmed_grade") is not None and c.get("test") is not None and t is not None
    skills, seen = [], set()
    for slug, (ok, n) in ((t or {}).get("skill_counts") or {}).items():
        tag = our_tag(slug)
        if tag and tag not in seen and n:
            seen.add(tag)
            skills.append({"tag": tag, "correct": ok, "total": n, "score": round(ok / n, 4)})
    decl = []
    for slug in c.get("declared_skills") or []:
        tag = our_tag(slug)
        if tag and tag not in decl:
            decl.append(tag)
    ach = []
    if c.get("fsp_tier") in FSP_MAP:
        lvl, place = FSP_MAP[c["fsp_tier"]]
        ach.append({"discipline": "algorithmic", "level": lvl, "place": place, "verified": True,
                    "event_name": "Соревнование ФСП"})
    dc = {
        "id": c["id"], "direction": d,
        "grade": our_grade(c["confirmed_grade"] if confirmed else c.get("claimed_grade")) or "middle",
        "grade_status": "confirmed" if confirmed else "unconfirmed",
        "theta": round(t["theta"] - THETA_SHIFT, 4) if confirmed else None,
        "se": t["error"] if confirmed else 0.35,
        "correct": t["correct"] if confirmed else None, "answered": t["total"] if confirmed else None,
        "work_format": "any", "city": None, "relocation": False,
        "skills": skills if confirmed else [], "declared_stack": decl + ([] if confirmed else [s["tag"] for s in skills if s["tag"] not in decl]),
        "achievements": ach, "probe_score": None,
    }
    b = _to_bundle(dc)
    if not b.profile.current_category_id:
        b.profile.current_direction_id = d  # ярус «не подтверждён»: направление из анкеты (как bench2.bundles_of)
    return b


def need_of(v: dict) -> dict:
    from app.modules.matching.need_parser import parse_need

    d = our_dir(v["specialization"])
    g = our_grade(v["grade"])
    phrases = [SKILL_PHRASE.get(s, s) for s in v["skills"]]
    text = f"{GRADE_TITLE.get(v['grade'], v['grade'])} {DIR_TITLE[DIR_MAP[v['specialization']]]}. Стек: {', '.join(phrases)}."
    return parse_need(text, d, g, use_llm=False)


def ndcg(gains: list[int]) -> float:
    def dcg(values):
        return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(values[:K]))

    ideal = dcg(sorted(gains, reverse=True))
    return dcg(gains) / ideal if ideal else 0.0


def evaluate(world: dict) -> dict:
    import bench2
    from app.modules.matching import ranking

    obs = world["observed"]
    cands = obs["candidates"]
    bundles_all = [to_bundle(c) for c in cands]
    in_cat = [k for k, b in enumerate(bundles_all) if b is not None]
    bundles = [bundles_all[k] for k in in_cat]
    rel = world["truth"]["relevance"]
    tg = world["truth"]["true_grade_idx"]
    st = world["rng_state_after_their_systems"]
    rng = random.Random()
    rng.setstate((st[0], tuple(st[1]), st[2]))
    p5, p10, nd, over, rr, per, parse_ok = [], [], [], [], [], [], []
    for j, v in enumerate(obs["vacancies"]):
        req = need_of(v)
        idx, above_id = bench2.pool_for(bundles, req)
        sub = [bundles[k] for k in idx]
        scored, _info = ranking.order_bundles(sub, req, dict(MODES[MODE]), above_id=above_id)
        back = {id(b): k for b, k in zip(sub, idx)}
        order = [back[id(x[1])] for x in scored]
        pos = {in_cat[k]: r for r, k in enumerate(order)}
        keys = [((1, -pos[i]) if i in pos else (0, 0)) for i in range(len(cands))]
        ranked = sorted(range(len(cands)), key=lambda i: (keys[i], rng.random()), reverse=True)
        gains = [rel[j][i] for i in ranked]
        p5.append(sum(g == 2 for g in gains[:5]) / 5)
        p10.append(sum(g == 2 for g in gains[:K]) / K)
        nd.append(ndcg(gains))
        target = world["truth"]["vacancy_grade_idx"][j]
        over.append(sum(tg[i] < target for i in ranked[:K]) / K)
        rr.append(next((1 / r for r, g in enumerate(gains, 1) if g == 2), 0.0))
        req_tags = sorted({s["tag"] for s in (req.get("stack_required") or []) + (req.get("stack_desired") or [])})
        parse_ok.append(req.get("direction") == our_dir(v["specialization"]) and req.get("grade") == our_grade(v["grade"]))
        per.append({"vacancy": v["id"], "spec": v["specialization"], "grade": v["grade"], "skills": v["skills"],
                    "parsed": {"direction": req.get("direction"), "grade": req.get("grade"), "tags": req_tags},
                    "pool": len(idx), "p5": p5[-1], "p10": p10[-1], "ndcg10": round(nd[-1], 6), "rr": round(rr[-1], 6),
                    "overrated10": over[-1]})
    return {
        "ours": {"p5": statistics.fmean(p5), "p10": statistics.fmean(p10), "ndcg10": statistics.fmean(nd),
                 "overrated10": statistics.fmean(over), "mrr": statistics.fmean(rr)},
        "parse_ok_share": sum(parse_ok) / len(parse_ok),
        "candidates_in_catalog": len(in_cat),
        "per_vacancy": per,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", required=True)
    ap.add_argument("--config", default="final", choices=sorted(CONFIGS))
    ap.add_argument("--mode", default="default", choices=sorted(MODES))
    ap.add_argument("--theta", default="last", choices=("pooled", "last"))
    ap.add_argument("--out")
    a = ap.parse_args()
    global THETA_SOURCE, MODE
    THETA_SOURCE = a.theta
    MODE = a.mode
    setup(a.config)
    world = json.loads(Path(a.world).read_text(encoding="utf-8"))
    res = evaluate(world)
    res.update(seed=world["seed"], config=a.config, mode=a.mode, theta=a.theta, their_commit=world["their_commit"], their=world["their_metrics"])
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("seed", "config", "mode", "theta", "ours", "parse_ok_share", "candidates_in_catalog")},
                     ensure_ascii=False))
    print(json.dumps({"their": res["their"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
