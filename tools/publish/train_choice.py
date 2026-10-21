"""Выбор одной конфигурации на TRAIN по правилу поправки №3 (раздел 3.7 протокола) — без ручного выбора.

Правило (записано до запуска раунда 2): среди кандидатов T* — минимум L = 3 · FC + FR (обе доли — от всех
кандидатов) при FC ≤ 2,5 %, p90 минут всего пути ≤ 105 и точном грейде (весь путь) не ниже T0 более чем на 1 п.п.;
при L в пределах 0,5 п.п. от лучшего — больше точный грейд, затем выше совпадение грейда при повторе, затем меньше
минут в среднем. Никто не прошёл ограничения — T0. S* (S-T-мир на TRAIN-зёрнах) — разведка, в выборе не участвуют.

    python3 tools/publish/train_choice.py docs/validation/train_2110b/SUMMARY.json --out docs/validation/TRAIN_CHOICE_2110b.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

FC_MAX, P90_MAX, EXACT_DROP_MAX, TIE = 0.025, 105.0, 0.01, 0.005
# Сравнения — в людях, а не в округлённых долях (замечание А15, P2): L_k = 3 · k_FC + k_FR; «в пределах 0,5 п.п.» —
# L_k ≤ лучший + 0,005 · N; «FC ≤ 2,5 %» — k_FC ≤ 0,025 · N; «точный грейд не ниже T0 более чем на 1 п.п.» — в людях.


def _k(v: dict, key: str) -> int | None:
    x, n = v.get(key), v.get("n")
    return None if x is None or not n else int(round(float(x) * int(n)))


def choose(summary: dict, prefix: str = "T", base: str = "T0") -> dict:
    rows = {k: v for k, v in summary.items() if k.startswith(prefix)}
    b = rows.get(base) or {}
    ex0 = b.get("exact_grade_final")
    table, ok = [], []
    for k, v in sorted(rows.items(), key=lambda kv: int(kv[0][len(prefix):]) if kv[0][len(prefix):].isdigit() else 99):
        p90 = (v.get("minutes_total") or {}).get("p90")
        why = []
        n = int(v.get("n") or 0)
        k_fc, k_fr, k_ex = _k(v, "false_confirm_all"), _k(v, "false_reject_all"), _k(v, "exact_grade_final")
        if k_fc is None or k_fc > FC_MAX * n:
            why.append(f"FC {k_fc} из {n} > {FC_MAX}")
        if p90 is None or p90 > P90_MAX:
            why.append(f"p90 {p90} > {P90_MAX}")
        if ex0 is not None and (k_ex is None or k_ex < (ex0 - EXACT_DROP_MAX) * n - 1e-9):
            why.append(f"точный грейд {v.get('exact_grade_final')} < {base} {ex0} − {EXACT_DROP_MAX}")
        r = {"config": k, "env": v.get("env"), "L": v.get("loss_3fc_fr"),
             "L_people": (3 * k_fc + k_fr) if k_fc is not None and k_fr is not None else None, "k_FC": k_fc, "k_FR": k_fr,
             "FC": v.get("false_confirm_all"),
             "FR": v.get("false_reject_all"), "exact_grade_final": v.get("exact_grade_final"),
             "exact_grade_final_5": v.get("exact_grade_final_5"), "retest_exact": v.get("retest_exact"),
             "retest_decision": v.get("retest_decision"), "retest_kappa_w": v.get("retest_kappa_w"),
             "confident_accuracy_final": v.get("confident_accuracy_final"),
             "confident_share_final": v.get("confident_share_final"), "undecided_final": v.get("undecided_final"),
             "minutes_total_mean": (v.get("minutes_total") or {}).get("mean"), "minutes_total_p90": p90,
             "n": v.get("n"), "passes": not why, "fails": why}
        table.append(r)
        if not why and r["L_people"] is not None:
            ok.append(r)
    if ok:
        best = min(ok, key=lambda r: r["L_people"] / r["n"])
        best_l = best["L"]
        near = [r for r in ok if r["L_people"] / r["n"] <= best["L_people"] / best["n"] + TIE + 1e-12]
        near.sort(key=lambda r: (-(r["exact_grade_final"] or 0), -(r["retest_exact"] or 0), r["minutes_total_mean"] or 1e9))
        chosen, reason = near[0]["config"], (f"минимум L = {best_l} среди прошедших ограничения; в пределах {TIE} — "
                                             f"{', '.join(r['config'] for r in near)}; из них больше точный грейд")
    else:
        chosen, reason = base, "ограничениям не отвечает никто — базовая конфигурация"
    return {"rule_ru": __doc__.split("\n\n")[1].replace("\n", " "), "chosen": chosen,
            "chosen_env": (rows.get(chosen) or {}).get("env"), "reason_ru": reason, "rows": table}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("summary")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    d = json.loads(Path(a.summary).read_text(encoding="utf-8"))
    res = choose(d["summary"])
    res["source"] = a.summary
    res["plan_seeds"] = (d.get("plan") or {}).get("seeds")
    res["command"] = f"python3 tools/publish/train_choice.py {a.summary} --out {a.out}"
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("chosen", "chosen_env", "reason_ru")}, ensure_ascii=False, indent=1))
    for r in res["rows"]:
        print(r["config"], "L", r["L"], "FC", r["FC"], "FR", r["FR"], "ex", r["exact_grade_final"], "rt", r["retest_exact"],
              "p90", r["minutes_total_p90"], "ok" if r["passes"] else r["fails"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
