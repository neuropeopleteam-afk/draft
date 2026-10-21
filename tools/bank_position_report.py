"""Сводка атак tools/bank_position_attack.py «до / после» → docs/bank/position_attack_2110.json.

Атаки делятся на две группы:
* позиционные (буква, ранг по величине и их пары с сюжетом) — должны быть на уровне случайного выбора: позиция ключа
  и его ранг задаются независимыми перестановками по блокам зёрен (_w2010_kit.slot);
* по форме (длина и текст варианта, их пары с буквой и сюжетом) — показывают, узнаётся ли ключ, если семейство уже
  видели или прочитали открытый код (утечкоустойчивость). Семейства с ≥ 90 % выведены (families_retired/form_leak_2110).

Запуск из корня репозитория:
    python3 tools/bank_position_report.py --before pos_before.json --after pos_after.json [--final pos_final.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

POS = ("letter", "value_rank", "letter_x_value_rank", "ctx_x_letter", "ctx_x_value_rank")
FORM = ("len_rank", "text", "letter_x_len_rank", "text_x_letter", "ctx_x_text")
REPO = Path(__file__).resolve().parents[1]


def _summ(d: dict) -> dict:
    fams = d["families"]
    out = {"n_families": d["n_families"], "train_seeds": d["train_seeds"], "test_seeds": d["test_seeds"],
           "key": d["key"], "by_attack": d["summary"]}
    for name, group in (("positional", POS), ("form", FORM)):
        ex = []
        for f in fams:
            vals = [f["by_attack"][a] - f["chance"] for a in group if a in f["by_attack"]]
            if vals:
                ex.append((max(vals), f["family_id"]))
        ex.sort(reverse=True)
        out[name] = {"attacks": list(group),
                     "n_families_excess_gt_0_10": sum(1 for e, _ in ex if e > 0.10),
                     "n_families_excess_gt_0_25": sum(1 for e, _ in ex if e > 0.25),
                     "n_families_acc_ge_0_90": sum(1 for f in fams if any(
                         f["by_attack"].get(a, 0) >= 0.90 for a in group)),
                     "top": [{"family_id": fid, "excess": round(e, 3)} for e, fid in ex[:15]]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--final", default="")
    ap.add_argument("--out", default=str(REPO / "docs" / "bank" / "position_attack_2110.json"))
    a = ap.parse_args()
    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))  # noqa: E731
    before, after = load(a.before), load(a.after)
    rep = {"command": after["command"],
           "rule": ("обучение на train случайных зёрнах из диапазона выдачи, проверка на test других; признаки варианта "
                    "без знания предмета: буква, ранг по величине, ранг по длине, текст (цифры → #), сюжет и их пары; "
                    "выбор — вариант с наибольшей долей «ключ» на обучении (ничья — доля); шанс — 1/k"),
           "before": {"tree": "7b30f54d (до правки _w2010_kit)", **_summ(before)},
           "after": {"tree": "после правки _w2010_kit (ac0c5eac), до вывода семейств по форме", **_summ(after)}}
    if a.final:
        rep["final"] = {"tree": "банк заморозки (после вывода 48 семейств и набора t21)", **_summ(load(a.final))}
    Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for k in ("before", "after", "final"):
        if k in rep:
            r = rep[k]
            print(k, r["n_families"], "позиционные >+10 п.п.:", r["positional"]["n_families_excess_gt_0_10"],
                  "≥90 %:", r["positional"]["n_families_acc_ge_0_90"], "| по форме >+10 п.п.:",
                  r["form"]["n_families_excess_gt_0_10"], "≥90 %:", r["form"]["n_families_acc_ge_0_90"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
