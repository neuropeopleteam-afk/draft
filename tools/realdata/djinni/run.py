"""Прогон конвейера подбора «Драфта» (match-v2 ветки А5, режим «без теста») на наборе Djinni + базовые линии.

Конвейер — продуктовая функция без изменений: app.modules.matching.bench_upload.evaluate_uploaded_dataset
(режим «Принесите свой набор»: parse_need → фильтр направления → score_candidate → must_have → core_skill →
selection_order). На каждую вакансию — один вызов: 1 вакансия + её пул CV. На вход — только тексты:
  вакансия: Position + "\n" + Long Description;  кандидат: Position + "\n" + CV.
Primary Keyword, Exp Years, Experience Years, English Level, компания и дата — скрыты (из них только метки).
θ не передаётся: все кандидаты — «грейд не подтверждён», навыки — заявленные (T0).

Режимы входа (--mode):
  pure    — продукт сам разбирает тексты (направление и грейд кандидата — parse_need продукта);
  adapter — направление/грейд вакансии и кандидата даёт адаптер (adapter.py); кандидаты «вне направлений» не грузятся.
Базовые линии на тех же пулах: BM25 (rank_bm25.BM25Okapi, запрос — текст вакансии, документы — тексты пула) и
случайный порядок (среднее по 100 перестановкам с фиксированным сидом).

  cd backend && LLM_DISABLED=true DATABASE_URL=sqlite:////tmp/a17.db \
      python ../tools/realdata/djinni/run.py <bench.json> <out.json> --mode adapter
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("LLM_DISABLED", "true")

import adapter  # noqa: E402
import metrics as M  # noqa: E402
from split import load  # noqa: E402

TOP = 50
TOKEN = re.compile(r"[a-z0-9#+]+(?:\.[a-z0-9]+)*")


def tok(s: str) -> list[str]:
    return TOKEN.findall(s.lower())


def texts(bench: dict) -> tuple[dict, dict]:
    jids = {v["id"] for v in bench["vacancies"]}
    cids = {c for v in bench["vacancies"] for c in v["pool"]}
    j = load("jobs")
    j = j[j["id"].isin(jids)]
    c = load("cvs")
    c = c[c["id"].isin(cids)]
    jt = {r.id: (r.Position or "", r._2 or "") for r in j.rename(columns={"Long Description": "_2"}).itertuples()}
    ct = {r.id: (r.Position or "", r.CV or "") for r in c.itertuples()}
    return jt, ct


def product_order(vid: str, jt: tuple, pool: list[str], ct: dict, mode: str, cache: dict, need_dir: str = "product",
                  need_grade: bool = False) -> tuple[list[str], dict]:
    from app.modules.matching.bench_upload import evaluate_uploaded_dataset

    title, body = jt
    need = {"id": vid, "title": title[:90], "text": f"{title}\n{body}"}
    cands = []
    for cid in pool:
        t, b = ct[cid]
        c = {"id": cid, "resume_text": f"{t}\n{b}"}
        if mode == "adapter":
            if cid not in cache:
                cache[cid] = (adapter.direction(t, b), adapter.grade(t, b))
            d, g = cache[cid]
            if d == "none":
                continue
            c["direction"] = d
            if g:
                c["grade"] = g
        cands.append(c)
    if need_dir == "title" and (d := adapter.title_direction(title)) in adapter.DIRECTIONS:
        need["direction"] = d  # название вакансии однозначно называет направление; иначе — разбор продукта
    if need_grade:
        need["grade"] = adapter.grade(title, body)
    if need_dir == "adapter":
        need["direction"] = None if (d := adapter.direction(title, body)) == "none" else d
        need["grade"] = adapter.grade(title, body)
    res = evaluate_uploaded_dataset(json.dumps({"needs": [need], "candidates": cands}, ensure_ascii=False), "json", k=TOP)
    pn = res["per_need"][0]
    info = {"parsed_direction": pn["requirements"]["direction"], "parsed_grade": pn["requirements"]["grade"],
            "stack_required": [s["tag"] for s in pn["requirements"]["stack_required"]],
            "uploaded": len(cands), "eligible": pn["eligible"]}
    return [r["candidate_id"] for r in pn["results"]], info


def bm25_order(jt: tuple, pool: list[str], ct: dict) -> list[str]:
    from rank_bm25 import BM25Okapi

    docs = [tok(f"{ct[c][0]}\n{ct[c][1]}") for c in pool]
    bm = BM25Okapi(docs)
    sc = bm.get_scores(tok(f"{jt[0]}\n{jt[1]}"))
    return [c for _, c in sorted(zip(sc, pool), key=lambda x: (-x[0], x[1]))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bench")
    ap.add_argument("out")
    ap.add_argument("--mode", choices=("pure", "adapter"), default="adapter")
    ap.add_argument("--need-dir", choices=("product", "title", "adapter"), default="product")
    ap.add_argument("--need-grade", action="store_true", help="грейд вакансии — адаптер (название или стаж в тексте)")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    bench = json.loads(Path(a.bench).read_text(encoding="utf-8"))
    vacs = bench["vacancies"][: a.limit or None]
    jt, ct = texts(bench)
    cache: dict = {}
    rows = {"draft": [], "bm25": [], "random": []}
    per = []
    t0 = time.time()
    for v in vacs:
        lab = v["labels"]
        allr = list(lab.values())
        order, info = product_order(v["id"], jt[v["id"]], v["pool"], ct, a.mode, cache, a.need_dir, a.need_grade)
        m_d = M.per_vacancy([lab[c] for c in order], allr)
        order_b = bm25_order(jt[v["id"]], v["pool"], ct)[:TOP]
        m_b = M.per_vacancy([lab[c] for c in order_b], allr)
        rng = random.Random(f"{bench['seed']}:random:{v['id']}")
        acc = {k: 0.0 for k in M.KEYS}
        for _ in range(100):
            p = v["pool"][:]
            rng.shuffle(p)
            for k, x in M.per_vacancy([lab[c] for c in p[:TOP]], allr).items():
                acc[k] += x / 100
        rows["draft"].append(m_d)
        rows["bm25"].append(m_b)
        rows["random"].append(acc)
        per.append({"id": v["id"], "category": v["category"], "exp_years": v["exp_years"], **info,
                    "draft": {k: round(x, 4) for k, x in m_d.items()}, "bm25": {k: round(x, 4) for k, x in m_b.items()},
                    "draft_top10": order[:10], "bm25_top10": order_b[:10]})
    seed = f"{bench['seed']}:{bench['part']}:boot"
    out = {"part": bench["part"], "mode": a.mode, "need_dir": a.need_dir, "need_grade": a.need_grade, "adapter": adapter.VERSION, "n_vacancies": len(vacs),
           "bench_sha256": bench["bench_sha256"], "seconds": round(time.time() - t0, 1),
           "flags": {k: os.environ.get(k) for k in ("MATCH_UNCONFIRMED_BY_CLAIM", "CATALOG_EXT_ENABLED", "MATCH_MUST_FIRST",
                                                     "RANK_CORE_SKILL", "MATCH_MUST_DECLARED", "NEED_TITLE_ROLE")},
           "summary": {s: M.summarize(r, seed) for s, r in rows.items()},
           "draft_minus_bm25": M.paired_diff(rows["draft"], rows["bm25"], seed + ":d"),
           "per_vacancy": per}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in rows:
        print(s, {k: v["mean"] for k, v in out["summary"][s].items()})
    print("seconds", out["seconds"])


if __name__ == "__main__":
    main()
