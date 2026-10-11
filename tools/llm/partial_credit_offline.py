"""Частичный балл 0–4 на уже сохранённых ответах оценщика — бесплатно, без новых запросов.

Те же 406 ответов набора оценщика (панель 06.10) и те же ответы модели-оценщика, что в замере доказательной оценки
(docs/llm/evidence_full.json): флаг GRADING_EVIDENCE выкл — промпт v2, вкл — промпт v3 + скептик + итог по правилам
кода. Балл 0–4 считается кодом из оценок пунктов рубрики (``partial_credit.points``) — тот же вызов оценщика, ответ
модели не меняется. Эталон честных ответов — gpt-oss-120b панели 06.10 (одна модель; модель, не люди), тоже в 0–4.

Что считается:
* согласие 0–4 с эталоном (κw, точное совпадение, ±1, MAE в баллах) и согласие «0/1» (порог 0,5: засчитано/нет);
* матрица ошибок оценщика P(балл оценщика | балл эталона) — модель шума оценщика для симуляции
  (``validation/partial_credit_sim``) → backend/app/modules/validation/data/partial_credit_noise.json;
* распределение баллов 0–4 у эталонов сильного/среднего/слабого ответа и у ответов моделей — используются ли
  промежуточные баллы 1–3 (без них 0–4 ничего не добавляет к 0/1).

    python tools/llm/partial_credit_offline.py           # → docs/llm/partial_credit_offline.json + data/partial_credit_noise.json

Каталоги сохранённых прогонов — переменные RULLM_DIR, STRONG_DIR, EVIDENCE_DIR (как у evidence_bench.py).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence_bench as EB  # noqa: E402

OUT = ROOT / "docs" / "llm" / "partial_credit_offline.json"
NOISE = ROOT / "backend" / "app" / "modules" / "validation" / "data" / "partial_credit_noise.json"


def _final_on(items: dict, rows: dict, ids: list[str]) -> tuple[dict, dict]:
    """Флаг вкл: первая оценка v3 и итог после скептика (как evidence_bench.report с --full)."""
    from app.modules.assessment import evidence as EV
    from app.modules.llm.client import _extract_json

    v3 = EB._read(EB.WDIR / "v3_full_out.jsonl")
    skq_path = EB.WDIR / "sk_full.jsonl"
    skq = {json.loads(x)["req_id"]: json.loads(x) for x in open(skq_path, encoding="utf-8")} if skq_path.exists() else {}
    sko = EB._read(EB.WDIR / "sk_full_out.jsonl")
    first, final = {}, {}
    for rid in ids:
        r = rows[rid]
        it = items[r["item"]]
        ans = EB._answer(r)
        p = EB._first(v3.get(rid), it, ans)
        if p is None:
            continue
        man = bool(p["manipulation"])
        first[rid] = {"score": None if man else p["score"], "criteria": p["criteria"], "manipulation": man}
        final[rid] = dict(first[rid])
        if man or rid not in skq or rid not in sko:
            continue
        so = sko[rid]
        sk = EV.parse_skeptic(_extract_json(so.get("text") or "") if not so.get("error") else None, it["rubric"])
        a = EV.assemble({"criteria": p["criteria"], "score": p["score"]}, sk, it["rubric"], ans, EB._task(it),
                        disagree=0.25, disputed=skq[rid]["disputed"])
        final[rid] = {"score": a["score"] if a["verdict"] in ("agree", "kept") else None,
                      "criteria": a["criteria"], "manipulation": a["verdict"] == "manipulation"}
    return first, final


def _off(items: dict, rows: dict, ids: list[str]) -> dict:
    res = EB._read(EB.SONNET_FULL)
    out = {}
    for rid in ids:
        if rid not in res:
            continue
        r = rows[rid]
        p = EB.parse(res[rid], items[r["item"]], EB._answer(r), "v2")
        if p.get("ok"):
            out[rid] = {"score": None if p["manipulation"] else p["score"], "criteria": p["criteria"],
                        "manipulation": bool(p["manipulation"])}
    return out


def agreement(scores: dict, ref: dict, rows: dict) -> dict:
    """0–4 и 0/1 против эталона на честных ответах (балл оценщика есть — не ушёл эксперту)."""
    from app.modules.assessment.partial_credit import points

    pairs = [(points(x["score"]), points(ref[r])) for r, x in scores.items()
             if r in ref and x.get("score") is not None and rows[r]["group"] in EB.HONEST]
    n = len(pairs)
    if not n:
        return {"n": 0}
    conf = [[0] * 5 for _ in range(5)]
    for g, e in pairs:
        conf[e][g] += 1
    bin01 = [(int(g >= 2), int(e >= 2)) for g, e in pairs]
    k01 = _kappa([(a * 4, b * 4) for a, b in bin01])
    return {"n": n, "kappa_w_0_4": round(_kappa(pairs), 3), "exact_0_4": round(sum(g == e for g, e in pairs) / n, 3),
            "within1_0_4": round(sum(abs(g - e) <= 1 for g, e in pairs) / n, 3),
            "mae_points": round(sum(abs(g - e) for g, e in pairs) / n, 3),
            "bias_points": round(sum(g - e for g, e in pairs) / n, 3),
            "agree_0_1": round(sum(a == b for a, b in bin01) / n, 3), "kappa_0_1": round(k01, 3),
            "confusion_ref_by_grader": conf}


def _kappa(pairs: list[tuple[int, int]], k: int = 5) -> float:
    n = len(pairs)
    obs = [[0] * k for _ in range(k)]
    for a, b in pairs:
        obs[int(a)][int(b)] += 1
    ra = [sum(obs[i]) for i in range(k)]
    rb = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    num = sum(((i - j) ** 2) * obs[i][j] for i in range(k) for j in range(k))
    den = sum(((i - j) ** 2) * ra[i] * rb[j] / n for i in range(k) for j in range(k))
    return 1 - num / den if den else 0.0


def noise_matrix(conf: list[list[int]], alpha: float = 0.5) -> list[list[float]]:
    """P(балл оценщика | балл эталона) со сглаживанием Лапласа α и запретом скачка > 2 баллов (в данных их нет)."""
    out = []
    for e, row in enumerate(conf):
        w = [(row[g] + alpha) if abs(g - e) <= 2 else 0.0 for g in range(5)]
        s = sum(w)
        out.append([round(v / s, 4) for v in w])
    return out


def main() -> int:
    from app.modules.assessment.partial_credit import points

    items, rows = EB._items_rows()
    ids = EB.run_ids(full=True)
    ref = {r: rows[r]["panel"]["gptoss"] for r in ids
           if (rows[r].get("panel") or {}).get("gptoss") is not None and rows[r]["group"] in EB.HONEST}
    off = _off(items, rows, ids)
    first, final = _final_on(items, rows, ids)
    dist: dict[str, list[int]] = {}
    for r, v in ref.items():
        g = rows[r]["group"]
        if g == "gptoss_answers":
            g = "gptoss_" + rows[r]["id"].split("|")[1]
        dist.setdefault(g, [0] * 5)[points(v)] += 1
    grader_dist: dict[str, list[int]] = {}
    for r, x in final.items():
        if x.get("score") is None or rows[r]["group"] not in EB.HONEST:
            continue
        grader_dist.setdefault(rows[r]["group"], [0] * 5)[points(x["score"])] += 1
    res = {
        "title": "Частичный балл 0–4 на сохранённых ответах оценщика (406 ответов набора 06.10, без новых запросов)",
        "grader": "Claude Sonnet 5.5", "skeptic": "Claude Fable 5.1",
        "reference": "gpt-oss-120b (панель 06.10, одна модель; модель, не люди)",
        "points_rule": "балл 0–4 = round(4 × взвешенная оценка пунктов рубрики); 0/1 — балл ≥ 2 (оценка ≥ 0,5)",
        "off_v2": agreement(off, ref, rows), "on_v3": agreement(first, ref, rows),
        "on_v3_skeptic": agreement(final, ref, rows),
        "reference_points_by_group": dist, "grader_points_by_group": grader_dist,
        "intermediate_share_reference": round(sum(v[1] + v[2] + v[3] for v in dist.values()) /
                                              max(1, sum(sum(v) for v in dist.values())), 3),
    }
    conf = res["on_v3_skeptic"]["confusion_ref_by_grader"]
    noise = {"source": "docs/llm/partial_credit_offline.json (on_v3_skeptic)", "grader": res["grader"],
             "reference": res["reference"], "n": res["on_v3_skeptic"]["n"],
             "matrix_ref_to_grader": noise_matrix(conf),
             "note": "строка — балл эталона 0–4, столбец — балл оценщика; сглаживание Лапласа 0,5, скачок > 2 запрещён"}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    NOISE.write_text(json.dumps(noise, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("reference_points_by_group",)}, ensure_ascii=False,
                     indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
