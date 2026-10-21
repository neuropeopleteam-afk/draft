"""Сборка набора «вакансия → пул 200 CV» для части dev или holdout (одинаковая процедура, разные сиды).

Отбор и метки — только по структурным полям Djinni (Primary Keyword, Exp Years, Experience Years); конвейеру они не
передаются (см. run.py: на вход — только тексты Position + Long Description / Position + CV).

* Категории (Primary Keyword), соответствующие направлениям «Драфта»: backend — Python, Java, .NET, PHP, Node.js,
  Golang; frontend — JavaScript; qa — QA, QA Automation; data_ml — Data Science; security — Security.
  Квота вакансий: QUOTA (всего 50).
* Вакансия годна, если Long Description ≥ 300 символов; повторы текста (первые 400 символов, нижний регистр) — одна.
* Пул на вакансию — 200 CV той же части: 50 той же категории, 75 других категорий наших направлений («трудные»
  отрицательные), 75 остальных категорий; CV годна, если CV ≥ 200 символов. Выбор — random.Random(seed:part:vacancy_id).
* Метки: 2 — та же категория и стаж CV в диапазоне вакансии; 1 — та же категория; 0 — остальное.
  Диапазон стажа по Exp Years: no_exp → [0; 2], Ny → [N; N+3] для N < 5, 5y → [5; ∞).
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from split import DJINNI_DIR, SEED, load, part_of, sha256_ids  # noqa: E402

CAT_DIRECTION = {"Python": "backend", "Java": "backend", ".NET": "backend", "PHP": "backend", "Node.js": "backend",
                 "Golang": "backend", "JavaScript": "frontend", "QA": "qa", "QA Automation": "qa",
                 "Data Science": "data_ml", "Security": "security"}
QUOTA = {"JavaScript": 5, "Java": 5, ".NET": 5, "Python": 5, "QA": 5, "QA Automation": 5,
         "PHP": 4, "Node.js": 4, "Golang": 4, "Data Science": 4, "Security": 4}
POOL = {"same": 50, "near": 75, "far": 75}
MIN_JOB, MIN_CV = 300, 200


def exp_range(code: str) -> tuple[float, float]:
    if code == "no_exp":
        return 0.0, 2.0
    n = float(code.rstrip("y"))
    return (n, float("inf")) if n >= 5 else (n, n + 3)


def label(job_cat: str, job_exp: str, cv_cat: str, cv_exp: float) -> int:
    if cv_cat != job_cat:
        return 0
    lo, hi = exp_range(job_exp)
    return 2 if lo <= cv_exp <= hi else 1


def build(part: str, scale: int = 1) -> dict:
    """scale > 1 — только для разработки: больше вакансий для настройки адаптера (отложенная часть — всегда 1)."""
    assert part in ("dev", "holdout") and (scale == 1 or part == "dev")
    jobs = load("jobs")
    cvs = load("cvs")
    jobs = jobs[jobs["id"].map(lambda i: part_of("jobs", i) == part)]
    cvs = cvs[cvs["id"].map(lambda i: part_of("cvs", i) == part)]
    jobs = jobs[jobs["Primary Keyword"].isin(QUOTA) & (jobs["Long Description"].str.len() >= MIN_JOB)]
    jobs = jobs.sort_values("id")
    jobs = jobs[~jobs["Long Description"].str[:400].str.lower().duplicated()]
    cvs = cvs[cvs["CV"].str.len() >= MIN_CV].sort_values("id")
    rng = random.Random(f"{SEED}:{part}:vacancies")
    chosen = []
    for cat, q in QUOTA.items():
        ids = jobs[jobs["Primary Keyword"] == cat]["id"].tolist()
        chosen += [(cat, i) for i in rng.sample(ids, q * scale)]
    by_cat = cvs.groupby("Primary Keyword")["id"].apply(list).to_dict()
    cv_cat = dict(zip(cvs["id"], cvs["Primary Keyword"]))
    cv_exp = dict(zip(cvs["id"], cvs["Experience Years"].astype(float)))
    jrow = jobs.set_index("id")
    ours = set(CAT_DIRECTION)
    vac = []
    for cat, jid in chosen:
        r = random.Random(f"{SEED}:{part}:pool:{jid}")
        near = [i for c in sorted(ours - {cat}) for i in by_cat.get(c, [])]
        far = [i for c in sorted(set(by_cat) - ours) for i in by_cat[c]]
        pool = r.sample(by_cat[cat], POOL["same"]) + r.sample(near, POOL["near"]) + r.sample(far, POOL["far"])
        r.shuffle(pool)
        exp = jrow.loc[jid, "Exp Years"]
        labels = {cid: label(cat, exp, cv_cat[cid], cv_exp[cid]) for cid in pool}
        vac.append({"id": jid, "category": cat, "direction": CAT_DIRECTION[cat], "exp_years": exp,
                    "pool": pool, "labels": labels})
    bench = {"part": part, "seed": SEED, "quota": QUOTA, "pool": POOL, "min_job_chars": MIN_JOB, "min_cv_chars": MIN_CV,
             "vacancies": vac}
    blob = json.dumps(bench, ensure_ascii=False, sort_keys=True).encode()
    bench["bench_sha256"] = hashlib.sha256(blob).hexdigest()
    bench["vacancy_ids_sha256"] = sha256_ids([v["id"] for v in vac])
    bench["cv_ids_sha256"] = sha256_ids({c for v in vac for c in v["pool"]})
    return bench


if __name__ == "__main__":
    part = sys.argv[1]
    scale = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    b = build(part, scale)
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else DJINNI_DIR / f"bench_{part}.json"
    dst.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    n2 = sum(1 for v in b["vacancies"] for x in v["labels"].values() if x == 2)
    n1 = sum(1 for v in b["vacancies"] for x in v["labels"].values() if x == 1)
    print(part, len(b["vacancies"]), "label2", n2, "label1", n1, b["bench_sha256"][:12])
