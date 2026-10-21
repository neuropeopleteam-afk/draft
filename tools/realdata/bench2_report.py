#!/usr/bin/env python3
"""Отчёт по прогону бенчмарка match-v2 на отложенных мирах: docs/realdata/bench_holdout2.json → BENCH_HOLDOUT2.md.

Все числа — из JSON-артефакта прогона (руками ничего не пишется). Таблицы: «было → стало» (match-v1.3 → match-v2),
выигрыш над четырьмя базами с парными 95 % ДИ, «с дозапросом» с ценой, по каждому миру, сверка определений.

  python3 tools/realdata/bench2_report.py [--src docs/realdata/bench_holdout2.json] [--out docs/realdata/BENCH_HOLDOUT2.md]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAMES = {"match_v2": "match-v2 (стало)", "match_v2_doz": "match-v2 + дозапрос, ответили 50 %",
         "match_v2_doz70": "match-v2 + дозапрос, ответили 70 % (справочно)", "match_v13": "match-v1.3 (было)",
         "bm25": "BM25 по резюме", "words_grade": "«слова + грейд» по анкете",
         "tfidf_filter": "TF-IDF по резюме с фильтром по заявленным направлению и грейду", "random": "случайный",
         "oracle_pool": "пул подборки по истинной метке (потолок, справочно)"}
COND = {"sm": "S-M «стандартные условия» (заголовок)", "hard": "жёсткие условия («проверка на прочность»)",
        "sm_ideal": "S-M, идеальный тест (справочно)", "sm_s55": "S-M, погрешность теста 0,55 (чувствительность)"}
M = ("p5", "p10", "ndcg10", "mrr", "top5_any", "over10")
MR = {"p5": "P@5", "p10": "P@10", "ndcg10": "nDCG@10", "mrr": "MRR", "top5_any": "≥ 1 в топ-5", "over10": "переоц. в топ-10"}


def f(x: float, pct: bool = False) -> str:
    return (f"{x * 100:.1f} %" if pct else f"{x:.3f}").replace(".", ",")


def ci(d: dict, pct: bool = False) -> str:
    return f"{f(d['mean'], pct)} [{f(d['lo'], pct)}; {f(d['hi'], pct)}]"


def table(P: dict, methods: list[str]) -> list[str]:
    out = ["| Метод | " + " | ".join(MR[k] for k in M) + " |", "|---|" + "---|" * len(M)]
    for m in methods:
        if m in P:
            out.append(f"| {NAMES[m]} | " + " | ".join(ci(P[m][k], k in ("top5_any", "over10")) for k in M if k in P[m]) + " |")
    return out


def gains(P: dict) -> list[str]:
    out = ["| match-v2 минус … | nDCG@10 | P@10 | P@5 | MRR |", "|---|---|---|---|---|"]
    for b in ("match_v13", "bm25", "words_grade", "tfidf_filter", "random"):
        if b in P:
            out.append(f"| {NAMES[b]} | " + " | ".join(ci(P[b][k]["diff_vs_match_v2"]) for k in ("ndcg10", "p10", "p5", "mrr")) + " |")
    return out


def render(d: dict) -> str:
    L = [f"# {d['what']}", "",
         f"Протокол `{d['protocol']}`, хэш FREEZE `{d['freeze_sha256']}`, коммит `{d['git_head'][:12]}`, "
         f"время {d['run_at']}, {d['seconds']} с. Миры: " + "; ".join(f"{COND.get(c, c)} — {', '.join(map(str, s))}"
                                                                  for c, s in d["worlds"].items()) + ".",
         "Синтетика — модели, не люди. 95 % ДИ — бутстрэп по потребностям (2 000 повторов); разности — парные.",
         "Команда: `python3 tools/realdata/bench_holdout2.py run` (повтор запрещён) → `python3 tools/realdata/bench2_report.py`.", ""]
    for c in ("sm", "hard", "sm_ideal", "sm_s55"):
        if c not in d["conditions"]:
            continue
        R = d["conditions"][c]["rel"]
        P = R["pooled"]
        L += [f"## {COND[c]}", "", f"Потребностей: {R['n_needs']}; метка — основная для этих условий (протокол, раздел «Истина»).", ""]
        L += table(P, ["match_v2", "match_v2_doz", "match_v2_doz70", "match_v13", "bm25", "words_grade", "tfidf_filter",
                       "random", "oracle_pool"])
        L += ["", "Выигрыш match-v2 (парный бутстрэп):", ""] + gains(P)
        dz = R["doz_vs_v2"]
        L += ["", "Дозапрос минус без дозапроса (ответили 50 %): " + "; ".join(
            f"{MR[k]} {ci(dz[k]['diff_vs_match_v2_doz'])}" for k in ("ndcg10", "p10", "p5", "mrr")) + "."]
        cost = [w.get("doz_cost") or {} for w in R["by_world"]]
        if cost and cost[0]:
            L += [f"Цена дозапроса: {cost[0].get('tasks_per_candidate')} заданий и {cost[0].get('minutes_per_candidate')} мин "
                  f"на кандидата; отправлено на потребность в среднем "
                  f"{f(sum(x.get('sent_per_need', 0) for x in cost) / len(cost))}, ответили "
                  f"{f(sum(x.get('answered_per_need', 0) for x in cost) / len(cost))}."]
        L += ["", "По мирам (match-v2 / match-v1.3 / BM25, nDCG@10; доля верно разобранных направления и грейда):", ""]
        for w in R["by_world"]:
            s = w["summary"]
            L.append(f"- зерно {w['seed']} ({w['n']} × {w['m']}): {f(s['match_v2']['ndcg10'])} / {f(s['match_v13']['ndcg10'])} / "
                     f"{f(s['bm25']['ndcg10'])}; P@10 {f(s['match_v2']['p10'])}; разбор {f(w['parse']['direction_ok'], True)} / "
                     f"{f(w['parse']['grade_ok'], True)}")
        if "l2" in d["conditions"][c]:
            P2 = d["conditions"][c]["l2"]["pooled"]
            L += ["", "Сверка определений — шкала 0–2 одного из аналогичных решений (те же веса, справочно):", ""]
            L += table(P2, ["match_v2", "match_v13", "bm25", "words_grade", "tfidf_filter"])
        L.append("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "docs/realdata/bench_holdout2.json"))
    ap.add_argument("--out", default=str(ROOT / "docs/realdata/BENCH_HOLDOUT2.md"))
    a = ap.parse_args()
    Path(a.out).write_text(render(json.loads(Path(a.src).read_text(encoding="utf-8"))), encoding="utf-8")
    print("записано:", a.out)
