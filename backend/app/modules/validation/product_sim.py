"""Симуляция ПРОДУКТА: тот же движок, что на стенде (BankEngine → AppCATSession → finish → вердикт →
второй этап у границы → итог двух этапов), на реальном банке заданий, с настройками стенда.

Чем отличается от прежних симуляций (замечания проверки 20.10, reviews/a4-method.md):
- задания, их параметры (a, b, разброс вариантов, время), пороги грейдов, правила выбора, остановки, дотестирования,
  вердикта и второго этапа — ровно те, что работают у кандидата (вызовы BankEngine.start/next_item/finish и
  two_stage.session_boundary/ext_params, как service.start_session);
- «истина» — отдельный поток случайных чисел: способность кандидата θ, его заявленный грейд, ответы (по модели 2PL с
  ИСТИННЫМИ параметрами задания) и время; движок их не видит — получает только 0/1 по частям задания и время;
- ответы оцениваются моделью ответа вместо проверки текста: это единственная подмена (текст и варианты в симуляции
  не нужны), поэтому генерация варианта кэшируется по семейству — на выбор задания и оценку она не влияет;
- зёрна обучения (подбор настроек) и отчёта разведены: TRAIN_SEEDS и TEST_SEEDS ниже, отчёт — только по TEST_SEEDS.

Два мира: «calibrated» — истинные параметры заданий совпадают с параметрами банка (условие «банк откалиброван»);
«misspec» — трудность семейств сдвинута N(0; 0,5) логита, наклоны умножены на lognormal(0; 0,25) (банк ещё не
откалиброван на людях — так и есть сейчас; движок об этом не знает).

Популяция — как в независимой модели аудита (docs/audit_2010/scripts/sim.py): θ ~ N(0; 1,3), заявленный грейд =
истинный + {0, 0, 0, +1, +1, −1} (треть завышает на ступень, шестая часть занижает); направление — равновероятно из
направлений банка; стек — 1–3 тега направления
(вероятность пропорциональна числу семейств банка с тегом), как в анкете кандидата.

Запуск (из backend/):
    python -m app.modules.validation.product_sim --phase test --world calibrated --n 3000 \
        --out app/modules/validation/data/product_sim_test_calibrated.json
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import datetime as dt
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import zlib

import numpy as np

# Профиль стенда fsp-draft.ru: /opt/spectrek_fsp/app/.env на 21.10.2026 + настройки, выбранные на обучающих зёрнах
# (product_sim_select.py → data/product_sim_train_selection.json; в .env.example — тот же блок). Остальные — значения
# по умолчанию app/core/config.py. Подставляются до импорта приложения, если не заданы в окружении.
STAND_ENV = {
    "ASSESSMENT_CONFIRM_LEVEL": "0.8",
    "ASSESSMENT_MAX_ITEMS": "20",
    "ASSESSMENT_TWO_STAGE_CONFIRM": "0.5",
    "ASSESSMENT_CODE_QUOTA_EXT": "true",
    "GRADES_EXT_ENABLED": "true",
    "ASSESSMENT_TWO_STAGE_ENABLED": "true",
    "GRADES_EXT_REFINE_ITEMS": "10",
    "GRADES_EXT_REFINE_MINUTES": "25",
    "CATALOG_EXT_ENABLED": "1",
    "LLM_DISABLED": "true",
    "ASSESSMENT_AI_MARK": "false",
}

TRAIN_SEEDS = tuple(range(1101, 1111))   # подбор настроек
TEST_SEEDS = tuple(range(2201, 2211))    # отчёт (до 21.10.2026 не использовались ни в одном прогоне)
THETA_SD = 1.3
CLAIM_SHIFT = (0, 0, 0, 1, 1, -1)
ORDER_ALL = ("none", "intern", "junior", "middle", "senior", "lead", "principal")
CODE_OPEN = {"find_bug", "predict_output", "choose_fix", "open_answer", "open_book_3step", "incident_sim",
             "code_fill", "code_trace", "write_code"}


def _rank(g: str | None) -> int:
    return ORDER_ALL.index(g) if g in ORDER_ALL else 0


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short=9", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


@dataclass
class World:
    seed: int
    kind: str  # calibrated | misspec

    def family_truth(self, fid: str) -> tuple[float, float]:
        """(множитель наклона, сдвиг трудности) семейства — постоянны в пределах мира."""
        if self.kind != "misspec":
            return 1.0, 0.0
        r = np.random.default_rng([self.seed, 2, zlib.crc32(fid.encode())])
        return float(r.lognormal(0.0, 0.25)), float(r.normal(0.0, 0.5))


class Sim:
    def __init__(self, world: World, rater_noise: float = 0.0, guessing: bool = True):
        from app.modules.assessment import bank_engine as be
        from app.modules.assessment import two_stage
        from app.modules.assessment.bank_engine import BankEngine
        from app.modules.catalog import levels

        self.be, self.two_stage, self.levels = be, two_stage, levels
        self.world = world
        self.rater_noise = float(rater_noise)
        self.guessing = bool(guessing)
        if not getattr(be, "_SIM_CACHE_PATCHED", False):  # генерация варианта на оценку не влияет — кэш по семейству
            orig = be.generate
            cache: dict[str, object] = {}

            def cached(fid, seed):
                if fid not in cache:
                    cache[fid] = orig(fid, seed)
                return cache[fid]

            be.generate = cached
            be._SIM_CACHE_PATCHED = True
        self.e = BankEngine()
        from app.modules.catalog.ext import visible_directions

        self.directions = list(visible_directions())
        # стек кандидата: 1–3 тега, без которых семейства направления не выдаются (как в анкете), с вероятностью,
        # пропорциональной числу таких семейств в банке; пустой стек отрезал бы почти все задания с кодом
        from assessment_bank import load_specs
        from app.modules.assessment.skill_map import stack_gate

        self.stack_tags: dict[str, Counter] = defaultdict(Counter)
        for sp in load_specs().values():
            if not sp.canary:
                for t in stack_gate(sp.direction, sp.skills):
                    self.stack_tags[sp.direction][t] += 1
        self.r_pop = np.random.default_rng([world.seed, 1])
        self.r_eng = np.random.default_rng([world.seed, 3])
        self.r_resp = np.random.default_rng([world.seed, 4])

    # -- кандидат
    def person(self) -> dict:
        d = self.directions[int(self.r_pop.integers(len(self.directions)))]
        order = ("none",) + tuple(self.levels.available_grades(d))
        theta = float(self.r_pop.normal(0.0, THETA_SD))
        from app.modules.catalog.seed_data import ALL_GRADE_CUTS

        g = "none"
        for gr in order[1:]:
            if theta >= ALL_GRADE_CUTS[gr]:
                g = gr
        gi = order.index(g)
        ci = int(np.clip(gi + CLAIM_SHIFT[int(self.r_pop.integers(len(CLAIM_SHIFT)))], 1, len(order) - 1))
        tags = self.stack_tags.get(d) or Counter()
        stack: list[str] = []
        if tags:
            names = sorted(tags)
            w = np.array([tags[t] for t in names], dtype=float)
            k = min(len(names), int(self.r_pop.integers(1, 4)))
            stack = [str(t) for t in self.r_pop.choice(names, size=k, replace=False, p=w / w.sum())]
        return {"direction": d, "theta": theta, "true_grade": g, "claim": order[ci], "order": order,
                "tau": float(self.r_pop.normal(0.0, 0.25)), "stack": stack}

    # -- одна сессия движка
    def run_session(self, st: dict, p: dict) -> None:
        e = self.e
        while True:
            it = e.next_item(st)
            if it is None:
                break
            cur = e._current(st)
            snap = cur["pool"]
            am, bs = self.world.family_truth(cur["family_id"])
            a = np.asarray(snap["a"], dtype=float) * am
            b = np.asarray(snap["b"], dtype=float) + bs + self.r_resp.normal(0.0, np.asarray(snap["sigma"], dtype=float))
            pr = 1.0 / (1.0 + np.exp(-a * (p["theta"] - b)))
            if self.guessing:  # люди угадывают: в части с выбором варианта c = 1/K (K — число вариантов этого шага)
                c = np.zeros(len(pr))
                for j in range(len(pr)):
                    if self.be.BankEngine._answer_kind(cur, j + 1) == "option":
                        opts = self.be.BankEngine._step_options(cur, j + 1) or []
                        c[j] = 1.0 / max(2, len(opts)) if opts else 0.0
                    elif self.be.BankEngine._answer_kind(cur, j + 1) == "line":
                        c[j] = 1.0 / max(2, int(cur["public"].get("code_lines") or 10))
                pr = c + (1.0 - c) * pr
            x = (self.r_resp.random(len(pr)) < pr).astype(float)
            if self.rater_noise > 0:
                for j in self.be.BankEngine.text_parts(cur):
                    if j - 1 < len(x) and self.r_resp.random() < self.rater_noise:
                        x[j - 1] = 1.0 - x[j - 1]
            t = float(np.exp(self.r_resp.normal(float(snap["beta_time"]) - p["tau"], 1.0 / float(snap["alpha_time"]))))
            t = max(5.0, min(t, float(cur["time_limit_s"])))
            cur["x"] = [float(v) for v in x]
            cur["done"], cur["time_s"], cur["log_t"], cur["overtime"] = True, t, math.log(t), False
            st["current"] = None

    def _seed(self) -> int:
        return int(self.r_eng.integers(1, 2**31 - 1))

    # -- путь кандидата в продукте: полный тест → (второй этап у границы) → итог
    def flow(self, p: dict, *, previous_subpools=None, seen=None, seen_seeds=None, two_stage_on: bool = True) -> dict:
        e, ts_mod = self.e, self.two_stage
        st = e.start(direction=p["direction"], claimed_grade=p["claim"], stack_tags=p["stack"], seed=self._seed(),
                     previous_subpools=previous_subpools or [], previous_families=[],
                     seen=seen or {}, seen_seeds=seen_seeds or {})
        self.run_session(st, p)
        res = e.finish(st)
        det = res.details or {}
        er = {"confirmed": res.confirmed, "provisional": res.provisional, "theta": res.theta, "se": res.se}
        ts = SimpleNamespace(status=_finished(), claimed_grade_id=p["claim"], direction_id=p["direction"],
                             result={"engine": e.name, "engine_result": er, "state": st, "mode": "full"})
        g_main = ts_mod.session_grade(ts)
        v = det.get("verdict") or {}
        done = [i for i in st["items"] if i.get("done") and not i.get("canary")]
        out = {"verdict_main": v.get("status"), "grade_main": g_main, "theta": res.theta, "se": res.se,
               "p_claimed": res.p_claimed, "n_main": len(done),
               "code_open_main": sum(1 for i in done if i["format"] in CODE_OPEN),
               "min_main": sum(float(i.get("time_s") or 0) for i in done) / 60.0,
               "stop": det.get("stop_reason"), "integrity_level": (det.get("integrity") or {}).get("level"),
               "oral": bool(v.get("oral_defense_required")), "refined": False, "grade_final": g_main,
               "min_refine": 0.0, "n_refine": 0, "subpool": st.get("subpool"),
               "families": [i["family_id"] for i in st["items"] if not i.get("canary")],
               "seeds": {i["family_id"]: i["seed"] for i in st["items"] if not i.get("canary")}}
        tp = ts_mod.params()
        b = ts_mod.session_boundary(ts, tp) if (two_stage_on and tp["enabled"]) else None
        out["boundary"] = b.as_dict() if b is not None else None
        if b is not None:
            p2 = ts_mod.ext_params(tp, b.cut_grade)
            prev = dict(st, final_theta=res.theta, final_se=res.se)
            seen2 = dict(seen or {})
            for f in out["families"]:
                seen2.setdefault(f, 0)
            seeds2 = {k: list(v) for k, v in (seen_seeds or {}).items()}
            for f, s in out["seeds"].items():
                seeds2.setdefault(f, []).append(int(s))
            st2 = e.start(direction=p["direction"], claimed_grade=p["claim"], stack_tags=p["stack"], seed=self._seed(),
                          refine_from=prev, seen=seen2, seen_seeds=seeds2,
                          refine={**b.as_dict(), "level": p2["level"], "items": int(p2["items"]),
                                  "minutes": int(p2["minutes"]), "confirm": p2["confirm"],
                                  "confirm_up": p2["confirm_up"], "floor": p2["floor"], "source_session_id": "sim"})
            self.run_session(st2, p)
            res2 = e.finish(st2)
            o = (res2.details or {}).get("two_stage") or {}
            new = [i for i in st2["items"] if i.get("done") and not i.get("canary")]
            out.update(refined=True, grade_final=o.get("final_grade") or "none",
                       n_refine=len(new), min_refine=sum(float(i.get("time_s") or 0) for i in new) / 60.0,
                       verdict_refine=((res2.details or {}).get("verdict") or {}).get("status"),
                       families=out["families"] + [i["family_id"] for i in new])
            for i in new:
                out["seeds"][i["family_id"]] = i["seed"]
        # «подтверждён» — только строгое подтверждение продукта: категория по основной части (confirmed) или итог второго
        # этапа не ниже заявки. «Junior (предварительно)» — НЕ подтверждение (работодатель видит пометку), считается отдельно
        out["provisional_main"] = bool(res.provisional)
        out["confirmed_final"] = (_rank(out["grade_final"]) >= _rank(p["claim"])) if out["refined"] else bool(res.confirmed)
        if out["provisional_main"] and not out["refined"]:
            out["grade_final_note"] = "provisional_junior"
        return out


def _finished():
    from app.core.enums import TestSessionStatus

    return TestSessionStatus.finished


# ---------------------------------------------------------------- метрики

def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    truth_ok = [r for r in rows if _rank(r["true_grade"]) >= _rank(r["claim"])]
    over = [r for r in rows if _rank(r["true_grade"]) < _rank(r["claim"])]
    acc = sum(1 for r in rows if r["confirmed_final"] == (_rank(r["true_grade"]) >= _rank(r["claim"])))
    fc = sum(1 for r in over if r["confirmed_final"])
    fr = sum(1 for r in truth_ok if not r["confirmed_final"])
    conf_main = [r for r in rows if r["verdict_main"] in ("confirmed", "not_confirmed")]
    conf_ok = sum(1 for r in conf_main
                  if (r["verdict_main"] == "confirmed") == (_rank(r["true_grade"]) >= _rank(r["claim"])))
    exact = sum(1 for r in rows if r["grade_final"] == r["true_grade"])
    gross = sum(1 for r in rows if abs(_rank(r["grade_final"]) - _rank(r["true_grade"])) >= 2)
    # «точный грейд» в той части шкалы, которую тест присваивает: кандидат не выше заявленного (тест не присваивает
    # грейд выше заявки — повышение предлагается отдельным тестом)
    capped = [r for r in rows if _rank(r["true_grade"]) <= _rank(r["claim"])]
    exact_c = sum(1 for r in capped if r["grade_final"] == r["true_grade"])
    mins_total = np.array([r["min_main"] + r["min_refine"] for r in rows]) if rows else np.zeros(1)
    mins_main = np.array([r["min_main"] for r in rows]) if rows else np.zeros(1)
    items = np.array([r["n_main"] for r in rows]) if rows else np.zeros(1)
    co = np.array([r["code_open_main"] / max(1, r["n_main"]) for r in rows]) if rows else np.zeros(1)
    refined = sum(1 for r in rows if r["refined"])
    prov = sum(1 for r in rows if r.get("provisional_main") and not r["refined"])
    prov_over = sum(1 for r in over if r.get("provisional_main") and not r["refined"])
    oral = sum(1 for r in rows if r["oral"])
    low_integ = sum(1 for r in rows if r.get("integrity_level") == "low")

    def frac(k, m):
        return {"k": k, "n": m, "value": round(k / m, 4) if m else None, "ci95": wilson(k, m)}

    return {
        "n": n,
        "verdict_accuracy_final": frac(acc, n),
        "false_confirm_among_overclaim": frac(fc, len(over)),
        "false_reject_among_true": frac(fr, len(truth_ok)),
        "confident_share_main": frac(len(conf_main), n),
        "confident_accuracy_main": frac(conf_ok, len(conf_main)),
        "followup_share": frac(refined, n),
        "provisional_junior_share": frac(prov, n),
        "provisional_among_overclaim": frac(prov_over, len(over)),
        "exact_grade_final": frac(exact, n),
        "exact_grade_final_not_above_claim": frac(exact_c, len(capped)),
        "gross_error_2plus": frac(gross, n),
        "oral_defense_share": frac(oral, n),
        "integrity_low_share_honest": frac(low_integ, n),
        "minutes_main": {"mean": round(float(mins_main.mean()), 1), "p90": round(float(np.percentile(mins_main, 90)), 1)},
        "minutes_total": {"mean": round(float(mins_total.mean()), 1), "p90": round(float(np.percentile(mins_total, 90)), 1)},
        "items_main": {"mean": round(float(items.mean()), 1), "min": int(items.min()), "max": int(items.max())},
        "code_open_share_main": {"mean": round(float(co.mean()), 3),
                                 "share_sessions_ge_one_third": round(float(np.mean(co >= 1 / 3 - 1e-9)), 4)},
    }


def by_claim(rows: list[dict]) -> dict:
    g = defaultdict(list)
    for r in rows:
        g[r["claim"]].append(r)
    out = {}
    for k in ORDER_ALL[1:]:
        if g.get(k):
            s = summarize(g[k])
            out[k] = {kk: s[kk] for kk in ("n", "verdict_accuracy_final", "false_confirm_among_overclaim",
                                           "confident_share_main", "confident_accuracy_main", "exact_grade_final",
                                           "minutes_total")}
    return out


def kappa_w(a: list[int], b: list[int], k: int) -> float | None:
    """Взвешенная каппа Коэна (квадратичные веса)."""
    if not a:
        return None
    o = np.zeros((k, k))
    for i, j in zip(a, b):
        o[i, j] += 1
    o /= o.sum()
    w = np.array([[(i - j) ** 2 for j in range(k)] for i in range(k)], dtype=float) / (k - 1) ** 2
    e = np.outer(o.sum(1), o.sum(0))
    den = (w * e).sum()
    return None if den == 0 else round(float(1 - (w * o).sum() / den), 4)


# ---------------------------------------------------------------- прогон

def run(phase: str, world_kind: str, n: int, seeds: tuple[int, ...], rater_noise: float = 0.0,
        retest: bool = False, two_stage_on: bool = True, progress: bool = True) -> dict:
    per_seed = max(1, n // len(seeds))
    rows: list[dict] = []
    rt_pairs: list[tuple[dict, dict]] = []
    errors: list[str] = []
    t0 = time.time()
    for s in seeds:
        sim = Sim(World(s, world_kind), rater_noise=rater_noise)
        for k in range(per_seed):
            p = sim.person()
            try:
                o = sim.flow(p, two_stage_on=two_stage_on)
            except Exception as ex:  # сбой движка — это находка, а не шум: считаем и показываем
                errors.append(f"{type(ex).__name__}: {ex}"[:200])
                continue
            rows.append({**{kk: p[kk] for kk in ("direction", "theta", "true_grade", "claim")},
                         **{kk: v for kk, v in o.items() if kk not in ("families", "seeds")}})
            if retest:
                seen = {f: 0 for f in o["families"]}
                seeds_ = {f: [int(v)] for f, v in o["seeds"].items()}
                try:
                    o2 = sim.flow(p, previous_subpools=[o["subpool"]] if o["subpool"] is not None else [],
                                  seen=seen, seen_seeds=seeds_, two_stage_on=two_stage_on)
                    rt_pairs.append((o, o2))
                except Exception as ex:
                    errors.append(f"retest {type(ex).__name__}: {ex}"[:200])
            if progress and (len(rows) % 100 == 0):
                print(f"[{phase}/{world_kind}] {len(rows)}/{per_seed * len(seeds)} · {time.time() - t0:.0f} с",
                      file=sys.stderr, flush=True)
    out = {"summary": summarize(rows), "by_claim": by_claim(rows),
           "claims": dict(Counter(r["claim"] for r in rows)),
           "true_grades": dict(Counter(r["true_grade"] for r in rows)),
           "engine_errors": {"n": len(errors), "examples": sorted(Counter(errors).items(), key=lambda kv: -kv[1])[:5]},
           "elapsed_s": round(time.time() - t0, 1)}
    if retest:
        a = [_rank(x["grade_final"]) for x, _ in rt_pairs]
        b = [_rank(y["grade_final"]) for _, y in rt_pairs]
        same = sum(1 for i, j in zip(a, b) if i == j)
        vsame = sum(1 for x, y in rt_pairs if x["confirmed_final"] == y["confirmed_final"])
        fam_overlap = [len(set(x["families"]) & set(y["families"])) for x, y in rt_pairs]
        out["retest"] = {"n_pairs": len(rt_pairs), "kappa_w_quadratic": kappa_w(a, b, len(ORDER_ALL)),
                         "exact_agreement": {"k": same, "n": len(a), "value": round(same / len(a), 4) if a else None,
                                             "ci95": wilson(same, len(a))},
                         "verdict_agreement": {"k": vsame, "n": len(a), "value": round(vsame / len(a), 4) if a else None,
                                               "ci95": wilson(vsame, len(a))},
                         "shared_families_mean": round(float(np.mean(fam_overlap)), 2) if fam_overlap else None}
    return out


def settings_snapshot() -> dict:
    from app.core.config import get_settings

    s = get_settings()
    keys = [k for k in type(s).model_fields if k.startswith(("assessment_", "grades_ext_"))]
    return {k: getattr(s, k) for k in sorted(keys)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--phase", choices=("train", "test"), required=True)
    ap.add_argument("--world", choices=("calibrated", "misspec"), default="calibrated")
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--rater-noise", type=float, default=0.0)
    ap.add_argument("--retest", action="store_true")
    ap.add_argument("--no-two-stage", action="store_true")
    ap.add_argument("--seeds", type=str, default="")
    ap.add_argument("--out", type=str, required=True)
    a = ap.parse_args(argv)
    seeds = tuple(int(x) for x in a.seeds.split(",")) if a.seeds else (TRAIN_SEEDS if a.phase == "train" else TEST_SEEDS)
    if a.phase == "test" and set(seeds) & set(TRAIN_SEEDS):
        raise SystemExit("отчёт только на зёрнах TEST_SEEDS")
    res = run(a.phase, a.world, a.n, seeds, rater_noise=a.rater_noise, retest=a.retest,
              two_stage_on=not a.no_two_stage)
    from app.modules.assessment.bank_engine import BankEngine

    e = BankEngine()
    meta = {
        "what": "симуляция продукта: движок стенда на реальном банке, модельные кандидаты (не люди)",
        "phase": a.phase, "world": a.world, "seeds": list(seeds), "n_requested": a.n,
        "rater_noise_text_parts": a.rater_noise, "two_stage": not a.no_two_stage,
        "responses": "2PL с истинными параметрами + угадывание c = 1/K в частях с выбором варианта (K — число вариантов шага), 1/строк для выбора строки",
        "population": {"theta": f"N(0; {THETA_SD})", "claim_shift": list(CLAIM_SHIFT), "stack": "1–3 тега направления, вероятность ∝ числу семейств банка с этим тегом"},
        "bank": {"n_families": e.n_families, "manifest": getattr(e, "manifest", None)},
        "settings": settings_snapshot(), "git_commit": _git_commit(),
        "date": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "command": "cd backend && python -m app.modules.validation.product_sim " + " ".join(argv or sys.argv[1:]),
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"meta": meta, **res}, ensure_ascii=False, indent=1, default=str) + "\n",
                           encoding="utf-8")
    print(json.dumps(res["summary"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    for k, v in STAND_ENV.items():
        os.environ.setdefault(k, v)
    raise SystemExit(main())
