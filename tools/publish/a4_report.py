"""Таблица отчёта А4 «было → стало» — только из двух версий docs/NUMBERS.json (без чисел руками).

    python3 tools/publish/a4_report.py --before a6f6b646f > docs/agents/a4_REPORT_TABLE.md

«Было» — NUMBERS.json на коммите --before (начало сессии 21.10, отчётный TEST-прогон на банке 1 504), «стало» —
текущий NUMBERS.json (итоговый прогон №2 на банке 1 646). Строки, которых раньше не было, помечены «новая метрика».
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _old(rev: str) -> dict:
    return json.loads(subprocess.check_output(["git", "-C", str(ROOT), "show", f"{rev}:docs/NUMBERS.json"], text=True))


def g(d, path):
    for k in path.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d.get("value") if isinstance(d, dict) and "value" in d else d


def pc(x):
    return "—" if x is None else f"{x * 100:.1f}".replace(".", ",") + " %"


def nm(x, k=3):
    return "—" if x is None else f"{x:.{k}f}".replace(".", ",")


ROWS = [  # (что, путь «было», путь «стало S-T», путь «стало жёсткие», формат, лучше: "up" / "down")
    ("Верный вердикт по заявке (все)", "grade_verdict.main.verdict_accuracy", "grade_verdict.st.view.verdict_accuracy",
     "grade_verdict.main.verdict_accuracy", "pct", "up"),
    ("Точность уверенного вердикта", "grade_verdict.main.confident_accuracy", "grade_verdict.st.extra.confident_accuracy_final",
     "grade_verdict.hard.extra.confident_accuracy_final", "pct", "up"),
    ("Доля уверенных вердиктов", "grade_verdict.main.confident_share", "grade_verdict.st.extra.confident_share_final",
     "grade_verdict.hard.extra.confident_share_final", "pct", "up"),
    ("Ложное подтверждение у завысивших", "grade_verdict.main.false_confirm", "grade_verdict.st.view.false_confirm",
     "grade_verdict.main.false_confirm", "pct", "down"),
    ("Ложное подтверждение от всех", "grade_verdict.main.false_confirm_all", "grade_verdict.st.extra.false_confirm_all",
     "grade_verdict.hard.extra.false_confirm_all", "pct", "down"),
    ("Точный грейд, 6 ступеней (все)", "grade_verdict.main.exact_grade", "grade_verdict.st.extra.exact_grade_all",
     "grade_verdict.hard.extra.exact_grade_all", "pct", "up"),
    ("Точный грейд, 4 ступени", None, "grade_verdict.st.extra.exact_grade_final_4", "grade_verdict.hard.extra.exact_grade_final_4",
     "pct", "up"),
    ("±1 ступень", "grade_verdict.main.within_one", "grade_verdict.st.extra.within_one_final",
     "grade_verdict.hard.extra.within_one_final", "pct", "up"),
    ("κw повтора", "grade_verdict.main.retest.kappa_w", "grade_verdict.st.extra.retest.kappa_w_quadratic",
     "grade_verdict.hard.extra.retest.kappa_w_quadratic", "num", "up"),
    ("То же решение при повторе", "grade_verdict.main.retest.verdict_agreement", "grade_verdict.st.extra.retest.decision_agreement",
     "grade_verdict.hard.extra.retest.decision_agreement", "pct", "up"),
    ("Решение вне ±0,25 от порога", None, "grade_verdict.st.extra.outside_0_25.verdict_accuracy_final",
     "grade_verdict.hard.extra.outside_0_25.verdict_accuracy_final", "pct", "up"),
    ("Утечка 100 вариантов: подтверждено слабых", "cheat_bots.leak_form.weak_leak_100", "cheat_bots.leak_form.weak_leak_100",
     "cheat_bots.leak_form.weak_leak_100", "pct", "down"),
    ("Банк: семейств", "bank.families", "bank.families", "bank.families", "int", "up"),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", default="a6f6b646f")
    a = ap.parse_args(argv)
    old, new = _old(a.before), json.loads((ROOT / "docs" / "NUMBERS.json").read_text(encoding="utf-8"))
    hm = ((new.get("grade_verdict") or {}).get("hard") or {}).get("extra") or {}
    sm = ((new.get("grade_verdict") or {}).get("st") or {}).get("extra") or {}
    f = {"pct": pc, "num": nm, "int": lambda x: "—" if x is None else f"{int(x):,}".replace(",", " ")}
    out = [f"# А4: таблица «было → стало» (генерируется tools/publish/a4_report.py --before {a.before})", "",
           f"Было — NUMBERS.json на {a.before} (отчётный TEST-прогон симуляции продукта, банк {g(old, 'bank.families')} "
           f"семейств). Стало — итоговый прогон №2 (поправки №3–4): стандартные условия S-T — заголовок, жёсткие — рядом; "
           f"время всего пути S-T {nm(g(sm, 'minutes_total.mean'), 1)} мин (p90 {nm(g(sm, 'minutes_total.p90'), 1)}), "
           f"жёсткие {nm(g(hm, 'minutes_total.mean'), 1)} мин (p90 {nm(g(hm, 'minutes_total.p90'), 1)}); N = 3 000 в "
           f"каждой строке, модельные кандидаты, не люди.", "",
           "| Метрика | Было | Стало: S-T | Стало: жёсткие | S-T выше / ниже |", "|---|---|---|---|---|"]
    for t, po, ps_, ph, fm, better in ROWS:
        b = g(old, po) if po else None
        s_, h = g(new, ps_), g(new, ph)
        if isinstance(b, dict):
            b = b.get("value")
        if isinstance(s_, dict):
            s_ = s_.get("value")
        if isinstance(h, dict):
            h = h.get("value")
        if b is None or s_ is None:
            cmp_ = "новая метрика" if b is None else "—"
        else:
            up = s_ > b
            cmp_ = "равно" if s_ == b else (("выше (лучше)" if up else "ниже (хуже)") if better == "up"
                                            else ("выше (хуже)" if up else "ниже (лучше)"))
        out.append(f"| {t} | {f[fm](b)} | {f[fm](s_)} | {f[fm](h)} | {cmp_} |")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
