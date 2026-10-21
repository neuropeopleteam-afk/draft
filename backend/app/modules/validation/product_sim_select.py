"""Выбор настроек продукта по обучающим прогонам симуляции (правило зафиксировано до прогонов —
docs/validation/PRODUCT_SIM_PROTOCOL.md): максимум точности итогового вердикта при «основная часть p90 ≤ 60 мин»
и «всего p90 ≤ 85 мин»; при равенстве в пределах 0,5 п.п. — меньше ложных подтверждений.

    python -m app.modules.validation.product_sim_select --dir <каталог train_*.json> --out data/product_sim_train_selection.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CONFIGS = {
    "C0": {"desc": "настройки стенда", "env": {}},
    "C1": {"desc": "квота практических заданий и в дотестировании", "env": {"ASSESSMENT_CODE_QUOTA_EXT": "true"}},
    "C2": {"desc": "C1 + порог подтверждения 0,8", "env": {"ASSESSMENT_CODE_QUOTA_EXT": "true", "ASSESSMENT_CONFIRM_LEVEL": "0.8"}},
    "C3": {"desc": "C2 + z 1,64", "env": {"ASSESSMENT_CODE_QUOTA_EXT": "true", "ASSESSMENT_CONFIRM_LEVEL": "0.8", "ASSESSMENT_CLASSIFY_Z": "1.64"}},
    "C4": {"desc": "C2 + SE-стоп 0,25", "env": {"ASSESSMENT_CODE_QUOTA_EXT": "true", "ASSESSMENT_CONFIRM_LEVEL": "0.8", "ASSESSMENT_SE_TARGET": "0.25"}},
    "C5": {"desc": "C2 + до 20 заданий", "env": {"ASSESSMENT_CODE_QUOTA_EXT": "true", "ASSESSMENT_CONFIRM_LEVEL": "0.8", "ASSESSMENT_MAX_ITEMS": "20"}},
    "C6": {"desc": "C2 + порог второго этапа 0,5", "env": {"ASSESSMENT_CODE_QUOTA_EXT": "true", "ASSESSMENT_CONFIRM_LEVEL": "0.8", "ASSESSMENT_TWO_STAGE_CONFIRM": "0.5"}},
    "C7": {"desc": "C2 + второй этап до 10 заданий", "env": {"ASSESSMENT_CODE_QUOTA_EXT": "true", "ASSESSMENT_CONFIRM_LEVEL": "0.8", "ASSESSMENT_TWO_STAGE_ITEMS": "10"}},
    # поправка 21.10 (мир с угадыванием, строгий критерий подтверждения) — отдельный раунд, сравнивать только между собой
    "G8": {"desc": "C8 в мире с угадыванием (оценка уровня без угадывания)", "env": {"ASSESSMENT_CODE_QUOTA_EXT": "true", "ASSESSMENT_CONFIRM_LEVEL": "0.8", "ASSESSMENT_MAX_ITEMS": "20", "ASSESSMENT_TWO_STAGE_CONFIRM": "0.5", "ASSESSMENT_GUESSING_3PL": "false"}},
    "G9": {"desc": "C8 + оценка уровня с угадыванием (3PL, c = 1/4)", "env": {"ASSESSMENT_CODE_QUOTA_EXT": "true", "ASSESSMENT_CONFIRM_LEVEL": "0.8", "ASSESSMENT_MAX_ITEMS": "20", "ASSESSMENT_TWO_STAGE_CONFIRM": "0.5", "ASSESSMENT_GUESSING_3PL": "true"}},
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--extra", default="", help="доп. конфигурации name=ENV1=v1;ENV2=v2,…")
    ap.add_argument("--rounds", default="C0,C1,C2,C3,C4,C5,C6,C7,C8|G8,G9", help="раунды через |; выбор — в последнем")
    a = ap.parse_args(argv)
    extra = {}
    for part in [p for p in a.extra.split(",") if p]:
        name, envs = part.split("=", 1)
        extra[name] = {"desc": "комбинация лучших одиночных изменений", "env": dict(kv.split(":", 1) for kv in envs.split(";"))}
    allc = {**CONFIGS, **extra}

    def load_round(names):
        rows = []
        for name in names:
            f = Path(a.dir) / f"train_{name}.json"
            if name not in allc or not f.exists():
                continue
            s = json.loads(f.read_text(encoding="utf-8"))["summary"]
            ok = s["minutes_main"]["p90"] <= 60 and s["minutes_total"]["p90"] <= 85
            rows.append({"config": name, **allc[name], "n": s["n"], "admissible": ok,
                         "verdict_accuracy": s["verdict_accuracy_final"]["value"],
                         "false_confirm": s["false_confirm_among_overclaim"]["value"],
                         "false_reject": s["false_reject_among_true"]["value"],
                         "confident_share": s["confident_share_main"]["value"],
                         "exact_grade": s["exact_grade_final"]["value"],
                         "minutes_main_p90": s["minutes_main"]["p90"], "minutes_total_p90": s["minutes_total"]["p90"],
                         "minutes_total_mean": s["minutes_total"]["mean"], "code_open_share": s["code_open_share_main"]["mean"]})
        return rows

    def choose(rows):
        adm = [r for r in rows if r["admissible"]]
        best = max(r["verdict_accuracy"] for r in adm)
        tied = [r for r in adm if r["verdict_accuracy"] >= best - 0.005]
        return min(tied, key=lambda r: (r["false_confirm"], -r["verdict_accuracy"]))

    rounds = [load_round(r.split(",")) for r in a.rounds.split("|")]
    rows = [dict(r, round=i + 1) for i, rr in enumerate(rounds) for r in rr]
    chosen = choose(rounds[-1])
    out = {"rule": "max точность итогового вердикта; p90 основной ≤ 60 мин, всего ≤ 85; при равенстве (0,5 п.п.) — меньше ложных подтверждений",
           "phase": "train (TRAIN_SEEDS)",
           "rounds_note": "раунд 1 — мир без угадывания (выбрано C8); раунд 2 — поправка 21.10: мир с угадыванием, строгий критерий подтверждения (сравнение только внутри раунда)",
           "rows": rows, "chosen": chosen["config"], "chosen_env": chosen["env"]}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"chosen": chosen["config"], "env": chosen["env"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
