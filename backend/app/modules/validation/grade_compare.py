"""Точность уровня в сопоставимых условиях (Я22, 11.10) → data/grade_compare.json, docs/validation/GRADE_COMPARE.md.

Та же процедура, что path-retest и перебор (grade_sweep.run_task: весь путь кандидата дважды, одни и те же
синтетические кандидаты во всех вариантах; модель, не люди), меняются только условия мира и разбор:

* мир «наш» — истинные параметры заданий = предкалибровка + ошибка эксперта σ = 0,5 (как на /validation);
* мир «точные параметры» — истина = предкалибровка без ошибки (так считают модели, где параметры заданий известны
  точно, — например, собственная симуляция ориентира);
* «заявили не ниже истинного» — подвыборка кандидатов, заявивших уровень не ниже своего истинного: тест подтверждает
  заявленный уровень и выше его не поднимает, поэтому заниженные заявления дают «ниже» независимо от точности теста;
* вариант ТЗ «справившийся уверенно — повысить грейд» без автоподъёма: короткий тест на уровень выше
  (grade_sweep.promote_path).

Продукт не меняется: все варианты — только в симуляции.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from app.modules.validation import grade_sweep as gs
from app.modules.validation import path_retest as pr
from app.modules.validation import sim
from app.modules.validation.signature import signature

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "grade_compare.json"
DOCS_MD = pr.REPO / "docs" / "validation" / "GRADE_COMPARE.md"

# варианты правила (все — при остальных параметрах продукта)
VARIANTS = {
    "old": {"confirm_level": 0.8},
    "current": {"confirm_level": 0.6},
    "promote_03": {"confirm_level": 0.6, "promote": 0.3},
    "promote_05": {"confirm_level": 0.6, "promote": 0.5},
    "promote_03_up08": {"confirm_level": 0.6, "promote": 0.3, "promote_up": 0.8},
    "promote_05_up09": {"confirm_level": 0.6, "promote": 0.5, "promote_up": 0.9},
}
VARIANT_RU = {"old": "прежнее правило (P ≥ 0,8)", "current": "действующее (P ≥ 0,6)",
              "promote_03": "P ≥ 0,6 + короткий тест на уровень выше при P(следующий) ≥ 0,3",
              "promote_05": "P ≥ 0,6 + короткий тест на уровень выше при P(следующий) ≥ 0,5",
              "promote_03_up08": "то же при P(следующий) ≥ 0,3, уровень выше — при P ≥ 0,8 по двум сессиям",
              "promote_05_up09": "то же при P(следующий) ≥ 0,5, уровень выше — при P ≥ 0,9 по двум сессиям"}
WORLDS = {"ours": {"misspec": 0.5}, "exact": {"misspec": 0.5, "exact": 1}}
WORLD_RU = {"ours": "наш мир: ошибка эксперта σ 0,5", "exact": "точные параметры заданий"}
FOUR = ("current", "promote_03_up08")  # + 4 ступени без Стажёра (как у ориентира) в мире точных параметров
OTHERS = [
    {"name": "Прототип А", "exact": 0.826, "kappa": 0.904, "over": 0.029,
     "note": "их материалы: собственная симуляция с точными параметрами заданий, 4 ступени"},
    {"name": "Прототип Б", "exact": 0.70, "note": "их материалы; условия расчёта не раскрыты"},
]
TWO_STAGE = {"exact": 0.675, "over": 0.040, "retest_exact": 0.80, "retest_kappa": 0.875,
             "note": "двухэтапное подтверждение пограничных (feat/two-stage, проба c₂ 0,5; синтетика)"}


def points() -> list[tuple[str, str, int, dict]]:
    out = []
    for w, wp in WORLDS.items():
        for v, vp in VARIANTS.items():
            out.append((w, v, 5, gs._p(**wp, **vp)))
    for v in FOUR:
        out.append(("exact", v, 4, gs._p(**WORLDS["exact"], **VARIANTS[v], levels=4)))
    return out


def _subset(rows: list[dict], mask_fn) -> list[dict]:
    keys = ("true", "claimed", "l1", "l2", "min1", "items1", "sess1", "border1", "status1", "offer1")
    out = []
    for r in rows:
        m = mask_fn(np.asarray(r["true"]), np.asarray(r["claimed"]))
        out.append({k: [x for x, keep in zip(r[k], m) if keep] for k in keys if k in r})
    return out


def block(rows: list[dict], seed: int) -> dict:
    m = gs.metrics(rows, seed=seed)
    cat = {k: np.concatenate([np.asarray(r[k]) for r in rows]) for k in ("true", "claimed", "l1", "offer1")}
    t, c, g = cat["true"], cat["claimed"], cat["l1"]
    m["claimed_below_share"] = round(float(np.mean(c < t)), 4)  # доля заявивших ниже истинного
    m["offered"] = round(float(np.mean(cat["offer1"].astype(bool))), 4) if len(cat["offer1"]) else 0.0
    m["promoted"] = round(float(np.mean([s == "promoted" for r in rows for s in r["status1"]])), 4)
    m["under_other"] = round(m["under"] - m["under_claimed_below"], 4)
    return m


def run(n: int = 500, workers: int | None = None, write: bool = True) -> dict:
    t0 = time.time()
    pts = points()
    tasks = [(p, i, d, n) for (_, _, _, p) in pts for i, d in enumerate(sim.DIRECTIONS)]
    import os

    workers = workers or min(8, len(os.sched_getaffinity(0)))
    print(f"вариантов: {len(pts)}, задач: {len(tasks)}, процессов: {workers}", flush=True)
    by: dict[str, list[dict]] = {}
    for r in gs.run_parallel(tasks, workers, t0):
        by.setdefault(r["key"], []).append(r)
    rows = []
    for w, v, lv, p in pts:
        rs = by[gs.key(p)]
        rows.append({"world": w, "variant": v, "levels": lv, "point": p,
                     "all": block(rs, pr.SEED),
                     "claimed_not_below": block(_subset(rs, lambda t, c: c >= t), pr.SEED)})
        a, b = rows[-1]["all"], rows[-1]["claimed_not_below"]
        print(f"  {w:5} {v:10} {lv} ступ.: точно {a['exact']:.3f} выше {a['over']:.3f} ниже {a['under']:.3f} "
              f"(заявили ниже {a['under_claimed_below']:.3f}) повтор {a['retest_exact']:.3f} κw {a['retest_kappa']:.3f} "
              f"мин {a['minutes_mean']:.1f} | не ниже: точно {b['exact']:.3f} выше {b['over']:.3f} "
              f"повтор {b['retest_exact']:.3f} κw {b['retest_kappa']:.3f}", flush=True)
    rep = {"signature": signature(seed=pr.SEED, config={"n": n, "variants": VARIANTS, "worlds": WORLDS,
                                                        "promote": gs.PROMOTE_CFG},
                                  n=n * len(sim.DIRECTIONS),
                                  world=f"симуляция всего пути (path-retest): {len(sim.DIRECTIONS)} направлений × {n} "
                                        f"синтетических кандидатов, путь дважды; миры: {', '.join(WORLD_RU.values())}",
                                  command="make grade-compare"),
           "rows": rows, "others": OTHERS, "two_stage": TWO_STAGE, "promote_cfg": gs.PROMOTE_CFG,
           "caveat": "Синтетика (модель, не люди): кандидаты — модель ответов 2PL; «точные параметры» — истина = "
                     "предкалибровка; числа ориентиров — из их материалов, другой мир и процедура.",
           "seconds": round(time.time() - t0, 1)}
    if write:
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        DOCS_MD.write_text(markdown(rep), encoding="utf-8")
        print(f"→ {OUT.relative_to(pr.REPO)}, {DOCS_MD.relative_to(pr.REPO)} ({rep['seconds']} с)", flush=True)
    return rep


def _pc(v) -> str:
    return "—" if v is None else f"{100 * v:.1f} %".replace(".", ",")


def _f(v, d: int = 3) -> str:
    return "—" if v is None else f"{v:.{d}f}".replace(".", ",")


def find(rep: dict, world: str, variant: str, levels: int = 5) -> dict | None:
    return next((r for r in rep["rows"] if r["world"] == world and r["variant"] == variant and r["levels"] == levels),
                None)


def markdown(rep: dict) -> str:
    sig = rep["signature"]
    head = ["| Условия | Вариант | Точно | Выше | Ниже (из них — заявили ниже) | Совпадение при повторе | κw повтора | "
            "Предложен тест выше / повышены | Минут (ср.) |", "|---|---|---|---|---|---|---|---|---|"]

    def line(r: dict, part: str) -> str:
        m = r[part]
        cond = WORLD_RU[r["world"]] + ("; 4 ступени без Стажёра" if r["levels"] == 4 else "") + \
            ("; заявили не ниже истинного" if part == "claimed_not_below" else "; все кандидаты")
        off = f"{_pc(m['offered'])} / {_pc(m['promoted'])}" if r["point"].get("promote") is not None else "—"
        ex_ci = f" [{_pc(m['exact_ci'][0])}; {_pc(m['exact_ci'][1])}]" if m.get("exact_ci") else ""
        return (f"| {cond} | {VARIANT_RU[r['variant']]} | {_pc(m['exact'])}{ex_ci} | {_pc(m['over'])} | "
                f"{_pc(m['under'])} ({_pc(m['under_claimed_below'])}) | {_pc(m['retest_exact'])} | "
                f"{_f(m['retest_kappa'])} | {off} | {_f(m['minutes_mean'], 1)} |")

    L = ["# Точность уровня в сопоставимых условиях", "",
         f"Подпись мира: {sig['world']}; seed {sig['seed']}, конфигурация `{sig['config_hash']}`, коммит "
         f"`{sig['commit']}`, банк `{sig['bank']}`. Пересчёт: `{sig['command']}`.", "",
         f"> {rep['caveat']}", "",
         "Процедура — та же, что «Весь путь дважды» на /validation (path-retest): опрос → заявленный уровень → "
         "адаптивный тест ≤ 60 мин → решение (подтверждён / доказанный уровень ниже / тест ступенью ниже); путь "
         "проходится дважды, «повтор» — совпадение итогов двух путей. Продукт не менялся.", "",
         "## (а)–(г): миры и подвыборки", "", *head]
    for w in WORLDS:
        for part in ("all", "claimed_not_below"):
            for v in VARIANTS:
                r = find(rep, w, v)
                if r:
                    L.append(line(r, part))
    four = [r for r in rep["rows"] if r["levels"] == 4]
    if four:
        L += ["", "## Как у ориентира: 4 ступени (без Стажёра), точные параметры", "", *head]
        L += [line(r, part) for part in ("all", "claimed_not_below") for r in four]
    cur, cur_x = find(rep, "ours", "current"), find(rep, "exact", "current")
    old = find(rep, "ours", "old")
    L += ["", "## Разбор промахов", ""]
    if old and cur:
        for name, r in (("прежнее правило (P ≥ 0,8), наш мир", old), ("действующее (P ≥ 0,6), наш мир", cur),
                        ("действующее, точные параметры", cur_x)):
            if not r:
                continue
            m = r["all"]
            L.append(f"- {name}: ниже {_pc(m['under'])} = {_pc(m['under_claimed_below'])} заниженных заявлений "
                     f"(заявили ниже истинного {_pc(m['claimed_below_share'])} кандидатов) + {_pc(m['under_other'])} "
                     f"ошибок теста; выше {_pc(m['over'])}; без категории {_pc(m['none'])}.")
    L += ["", "## Сравнение с другими (их числа — из их материалов; другой мир и процедура)", "",
          "| Источник | Точно | Выше | κw | Условия |", "|---|---|---|---|---|"]
    for c in rep["others"]:
        L.append(f"| {c['name']} | {_pc(c.get('exact'))} | {_pc(c.get('over'))} | {_f(c.get('kappa'))} | {c['note']} |")
    ts = rep["two_stage"]
    L.append(f"| Двухэтапное подтверждение (наш вариант) | {_pc(ts['exact'])} | {_pc(ts['over'])} | "
             f"{_f(ts['retest_kappa'])} | {ts['note']}; повтор {_pc(ts['retest_exact'])} |")
    for w in WORLDS:
        for part in ("all", "claimed_not_below"):
            r = find(rep, w, "current")
            if r:
                m = r[part]
                L.append(f"| Драфт, {VARIANT_RU['current']} | {_pc(m['exact'])} | {_pc(m['over'])} | "
                         f"{_f(m['retest_kappa'])} | {WORLD_RU[w]}; "
                         f"{'заявили не ниже истинного' if part != 'all' else 'все кандидаты'} |")
    pc = rep["promote_cfg"]
    L += ["", "## Вариант ТЗ «справившийся уверенно — повысить грейд»", "",
          f"Не автоподъём: подтвердившему заявленный уровень, у которого P(θ ≥ порога следующего) ≥ q, сразу "
          f"предлагается короткий тест на уровень выше ({pc['min_items']}–{pc['max_items']} заданий, ≤ "
          f"{pc['max_minutes']} мин, без повторов семейств). Следующий уровень — если общая оценка двух сессий "
          f"(нормальное приближение произведения правдоподобий) даёт P ≥ 0,6 (в вариантах «уровень выше — при P ≥ 0,8/0,9» — "
          f"строже); иначе остаётся подтверждённый. Кандидат "
          f"в модели принимает предложение всегда — это верхняя оценка эффекта. Минуты — сумма сессий пути.", "",
          "Пересчёт: `make grade-compare` (≈ 1–2 мин на 8 ядрах).", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Точность уровня в сопоставимых условиях → data/grade_compare.json")
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--md-only", action="store_true")
    a = ap.parse_args()
    if a.md_only:
        DOCS_MD.write_text(markdown(json.loads(OUT.read_text(encoding="utf-8"))), encoding="utf-8")
        return 0
    run(a.n, a.workers, not a.no_write)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
