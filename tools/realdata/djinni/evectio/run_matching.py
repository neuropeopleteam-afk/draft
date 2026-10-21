"""Наш подбор «один в один» на открытом формате внешней оценки соседней команды (Эвектио, MIT).

Источник: github.com/archebaldo777/sporthackathon @85bbc78, docs/examples/eval_pairs_example.json
(48 вакансий, 620 кандидатов, 5728 пар с оценкой 0–3). Метрики — их же функция _metrics
(backend/app/validation/external_eval.py, импортируется из клона по зафиксированному коммиту),
протоколы — их же: «по всей базе» (пул = все кандидаты) и «только размеченные пары».

Наш продукт вызывается ровно так, как его вызывает экран «Принесите свой набор»:
app.modules.matching.bench_upload.evaluate_uploaded_dataset(json, k=50). Код продукта не меняется.

Конфигурации (обе объявлены в PROTOCOL до прогона, заголовок — B):
  A «как есть»       — их файл без изменений (поля, которых наш формат не знает, продукт игнорирует);
  B «перевод полей»  — переименование их полей в поля нашего формата (правила — в to_ours_b, без
                       обучения и без порогов): test.grade→grade, test.theta→theta, test.verified_skills→skills,
                       fsp→achievements, work_formats→work_format, метки vacancy/candidate→need_id/candidate_id.

Запуск:  python run_matching.py --part dev|holdout --src <клон> [--out file.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import statistics
import sys
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "../../../.."))
sys.path.insert(0, os.path.join(REPO, "backend"))
os.environ.setdefault("LLM_DISABLED", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/a17_evectio.db")

SALT = "a17-evectio-2110"
SRC_COMMIT = "85bbc78"
EXAMPLE = "docs/examples/eval_pairs_example.json"
SHARED_SPECS = {"Backend-разработка", "Frontend-разработка", "QA / Тестирование", "Data Science / ML", "Информационная безопасность"}
K_ROWS = 50  # продукт отдаёт до 50 строк выдачи; MRR и R@30 считаются по ним (обрезка MRR ≤ 0,02 на вакансию)


K = 10


def their_metrics(ranked: list[str], rel: dict[str, int], thr: int, pool_size: int) -> dict:
    """Дословная копия _metrics из их backend/app/validation/external_eval.py @85bbc78 (MIT) — одна формула для всех."""
    rels = [rel.get(i, 0) for i in ranked]
    k = max(1, min(K, pool_size))
    gains = [2 ** r - 1 for r in rels[:K]]
    ideal = sorted((2 ** r - 1 for r in rel.values()), reverse=True)[:K]
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    relevant_total = sum(1 for v in rel.values() if v >= thr)
    first = next((i for i, r in enumerate(rels) if r >= thr), None)
    return {
        "p@10": sum(1 for r in rels[:k] if r >= thr) / k,
        "ndcg@10": dcg / idcg if idcg > 0 else 0.0,
        "mrr": 1 / (first + 1) if first is not None else 0.0,
        "recall@30": sum(1 for r in rels[:30] if r >= thr) / relevant_total if relevant_total else 0.0,
    }


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def spec_of(v: dict) -> str:
    """Направление вакансии в их формате — первая часть текста до « (»; нужно только для стратификации разбиения."""
    return v["text"].split(" (", 1)[0].strip()


def split(vacancies: list[dict]) -> dict[str, list[str]]:
    """РАЗРАБОТКА: по одной вакансии каждого их направления (наименьший sha256(SALT:id)); остальное — ОТЛОЖЕННАЯ."""
    by: dict[str, list[str]] = {}
    for v in vacancies:
        by.setdefault(spec_of(v), []).append(str(v["id"]))
    dev = sorted(min(ids, key=lambda i: hashlib.sha256(f"{SALT}:{i}".encode()).hexdigest()) for ids in by.values())
    hold = sorted(str(v["id"]) for v in vacancies if str(v["id"]) not in dev)
    return {"dev": dev, "holdout": hold}


def to_ours_b(c: dict) -> dict:
    t = c.get("test") or {}
    out = {"id": c["id"], "resume_text": c.get("resume_text") or "", "city": c.get("city")}
    if t.get("grade"):
        out["grade"] = t["grade"]
        if t.get("theta") is not None:
            out["theta"] = t["theta"]
        out["skills"] = list(t.get("verified_skills") or [])
    elif c.get("grade"):
        out["grade"] = c["grade"]
    wf = c.get("work_formats") or []
    out["work_format"] = wf[0] if len(wf) == 1 else "any"
    ach = []
    for a in c.get("fsp") or []:
        ach.append({"discipline": a.get("discipline"), "level": a.get("level"), "place": a.get("place"),
                    "event_name": a.get("event")})
    if ach:
        out["achievements"] = ach
    return out


def product_rank(vacancies: list[dict], candidates: list[dict], labels: list[dict] | None) -> tuple[dict[str, list[str]], dict]:
    from app.modules.matching.bench_upload import evaluate_uploaded_dataset

    payload = {"vacancies": vacancies, "candidates": candidates}
    if labels is not None:
        payload["labels"] = labels
    res = evaluate_uploaded_dataset(json.dumps(payload, ensure_ascii=False), "json", k=K_ROWS)
    ranked = {str(n["need_id"]): [str(r["candidate_id"]) for r in n["results"]] for n in res["per_need"]}
    meta = {str(n["need_id"]): {"requirements": n["requirements"], "eligible": n["eligible"]} for n in res["per_need"]}
    return ranked, {"per_need": meta, "summary": res.get("summary")}


def boot_ci(xs: list[float], n: int = 2000, seed: int = 17) -> list[float]:
    rnd = random.Random(seed)
    ms = sorted(statistics.mean(rnd.choice(xs) for _ in xs) for _ in range(n))
    return [round(ms[int(0.025 * n)], 3), round(ms[int(0.975 * n) - 1], 3)]


def boot_diff_ci(a: list[float], b: list[float], n: int = 2000, seed: int = 17) -> list[float]:
    rnd = random.Random(seed)
    idx = range(len(a))
    ms = []
    for _ in range(n):
        s = [rnd.choice(idx) for _ in idx]
        ms.append(statistics.mean(a[i] - b[i] for i in s))
    ms.sort()
    return [round(ms[int(0.025 * n)], 3), round(ms[int(0.975 * n) - 1], 3)]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["dev", "holdout"], required=True)
    ap.add_argument("--src", required=True, help="клон их репозитория на коммите 85bbc78")
    ap.add_argument("--their-python", required=True, help="python их окружения (requirements.txt их backend)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)

    path = os.path.join(a.src, EXAMPLE)
    data = json.load(open(path, encoding="utf-8"))
    sp = split(data["vacancies"])
    part_ids = set(sp[a.part])
    vacs = [v for v in data["vacancies"] if str(v["id"]) in part_ids]
    labs = [lb for lb in data["labels"] if str(lb["vacancy"]) in part_ids]
    rel: dict[str, dict[str, int]] = {str(v["id"]): {} for v in vacs}
    for lb in labs:
        rel[str(lb["vacancy"])][str(lb["candidate"])] = int(lb["relevance"])
    thr = 2
    cand_ids = [str(c["id"]) for c in data["candidates"]]

    # Их ранжировщик и их базовая линия на ТОМ ЖЕ подмножестве вакансий (их код и их окружение, кандидаты целиком)
    t0 = time.time()
    ids_f, th_f = f"/tmp/a17_ev_ids_{a.part}.json", f"/tmp/a17_ev_their_{a.part}.json"
    json.dump(sorted(part_ids), open(ids_f, "w"))
    subprocess.run([a.their_python, os.path.join(HERE, "their_eval.py"), "--src", a.src, "--ids", ids_f, "--out", th_f],
                   check=True, cwd=os.path.join(a.src, "backend"))
    theirs = json.load(open(th_f, encoding="utf-8"))
    their_rows = {r["vacancy"]: r for r in theirs["per_vacancy"]}
    evaluated = [str(v["id"]) for v in vacs if any(x >= thr for x in rel[str(v["id"])].values())]

    configs = {
        "A_as_is": (lambda c: c, None),
        "B_mapped": (to_ours_b, [{"need_id": lb["vacancy"], "candidate_id": lb["candidate"], "relevance": lb["relevance"]} for lb in labs]),
    }
    out: dict = {
        "source": {"repo": "github.com/archebaldo777/sporthackathon", "commit": SRC_COMMIT, "file": EXAMPLE,
                   "sha256": sha256_file(path), "license": "MIT",
                   "their_eval_sha256": sha256_file(os.path.join(a.src, "backend/app/validation/external_eval.py"))},
        "split": {"salt": SALT, "dev": sp["dev"], "holdout_n": len(sp["holdout"]), "part": a.part},
        "threshold": thr, "vacancies": len(vacs), "vacancies_evaluated": len(evaluated),
        "candidates": len(cand_ids), "labels": len(labs), "k_rows": K_ROWS,
        "configs": {},
    }
    per_vac: dict[str, dict] = {vid: {"their": their_rows[vid]["pool"]["ours"], "their_keyword": their_rows[vid]["pool"]["keyword_baseline"],
                                      "their_pairs": their_rows[vid]["pairs"]["ours"],
                                      "their_parsed": their_rows[vid]["parsed"]} for vid in evaluated}
    for name, (conv, labels_ours) in configs.items():
        cands = [conv(c) for c in data["candidates"]]
        # пул: все кандидаты, все вакансии части — один вызов продукта
        ranked_pool, meta = product_rank(vacs, cands, labels_ours)
        # размеченные пары: для каждой вакансии — только её размеченные кандидаты
        by_id = {str(c["id"]): c for c in cands}
        pool_m, pairs_m = [], []
        for vid in evaluated:
            v = next(x for x in vacs if str(x["id"]) == vid)
            lab_ids = list(rel[vid])
            rp, _ = product_rank([v], [by_id[c] for c in lab_ids], None)
            mp = their_metrics(ranked_pool.get(vid, []), rel[vid], thr, len(cand_ids))
            mq = their_metrics(rp.get(vid, []), rel[vid], thr, len(lab_ids))
            pool_m.append(mp)
            pairs_m.append(mq)
            per_vac[vid].setdefault("ours", {})[name] = {"pool": {k: round(x, 3) for k, x in mp.items()},
                                                          "pairs": {k: round(x, 3) for k, x in mq.items()},
                                                          "requirements": meta["per_need"].get(vid, {}).get("requirements"),
                                                          "eligible": meta["per_need"].get(vid, {}).get("eligible")}
        conf = {"pool": {}, "pairs": {}, "product_builtin_summary": meta["summary"]}
        for proto, ms, key in (("pool", pool_m, "pool"), ("pairs", pairs_m, "pairs")):
            for metric in ("p@10", "ndcg@10", "mrr", "recall@30"):
                ours = [m[metric] for m in ms]
                th = [their_rows[vid][key]["ours"][metric] for vid in evaluated]
                kw = [their_rows[vid][key]["keyword_baseline"][metric] for vid in evaluated]
                conf[proto][metric] = {"ours": round(statistics.mean(ours), 3), "ours_ci95": boot_ci(ours),
                                       "their": round(statistics.mean(th), 3), "their_keyword": round(statistics.mean(kw), 3),
                                       "ours_minus_their": round(statistics.mean(ours) - statistics.mean(th), 3),
                                       "ours_minus_their_ci95": boot_diff_ci(ours, th),
                                       "ours_minus_keyword": round(statistics.mean(ours) - statistics.mean(kw), 3)}
        conf["wins_ndcg10_pool_vs_their"] = {
            "wins": sum(1 for vid in evaluated if per_vac[vid]["ours"][name]["pool"]["ndcg@10"] > round(their_rows[vid]["pool"]["ours"]["ndcg@10"], 3)),
            "ties": sum(1 for vid in evaluated if per_vac[vid]["ours"][name]["pool"]["ndcg@10"] == round(their_rows[vid]["pool"]["ours"]["ndcg@10"], 3)),
            "n": len(evaluated)}
        # Срез «общие направления»: вакансии их направлений, которые есть и у нас (их направлений 8, наших 5)
        sh = [i for i, vid in enumerate(evaluated) if spec_of(next(x for x in vacs if str(x["id"]) == vid)) in SHARED_SPECS]
        conf["shared_directions"] = {"n": len(sh), "pool": {}}
        for metric in ("p@10", "ndcg@10", "mrr", "recall@30"):
            o = [pool_m[i][metric] for i in sh]
            th = [their_rows[evaluated[i]]["pool"]["ours"][metric] for i in sh]
            kw = [their_rows[evaluated[i]]["pool"]["keyword_baseline"][metric] for i in sh]
            if sh:
                conf["shared_directions"]["pool"][metric] = {"ours": round(statistics.mean(o), 3), "ours_ci95": boot_ci(o),
                                                             "their": round(statistics.mean(th), 3), "their_keyword": round(statistics.mean(kw), 3),
                                                             "ours_minus_their_ci95": boot_diff_ci(o, th)}
        out["configs"][name] = conf
    out["their_summary"] = theirs["summary"]
    out["per_vacancy"] = per_vac
    out["elapsed_s"] = round(time.time() - t0, 1)
    js = json.dumps(out, ensure_ascii=False, indent=1)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(js)
    for name, conf in out["configs"].items():
        for proto in ("pool", "pairs"):
            print(name, proto, {m: (v["ours"], v["their"], v["their_keyword"]) for m, v in conf[proto].items()})
    print("elapsed", out["elapsed_s"])


if __name__ == "__main__":
    main()
