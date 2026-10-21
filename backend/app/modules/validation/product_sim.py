"""Симуляция ПРОДУКТА: тот же движок, что на стенде (BankEngine → AppCATSession → finish → вердикт → второй этап у
порога → устная защита), на реальном банке заданий, с настройками стенда. Поправка №2 протокола (21.10 вечер):
решение по заявленному грейду — SPRT у порога заявленного грейда по ответам (без априорного стягивания), продление у
спорного порога, второй этап — продолжение того же SPRT, затем — устная защита (в симуляции — консервативная модель),
«уровень по ответам» — оценка Уорма (WLE). Протокол — docs/validation/PRODUCT_SIM_PROTOCOL.md.

Чем отличается от прежних симуляций (замечания проверки 20.10, reviews/a4-method.md):
- задания, их параметры (a, b, разброс вариантов, время), пороги грейдов, правила выбора, остановки, вердикта и второго
  этапа — ровно те, что работают у кандидата (вызовы BankEngine.start/next_item/finish и two_stage.session_boundary /
  ext_params, как service.start_session);
- «истина» — отдельный поток случайных чисел: способность кандидата θ, его заявленный грейд, ответы (по модели 3PL с
  ИСТИННЫМИ параметрами задания и угадыванием 1/K по фактическому числу вариантов) и время; движок их не видит —
  получает только 0/1 по частям задания и время;
- ответы оцениваются моделью ответа вместо проверки текста (единственная подмена; генерация варианта кэшируется по
  семейству — на выбор задания и оценку она не влияет);
- зёрна обучения (подбор настроек) и отчёта разведены: TRAIN_SEEDS, TEST_SEEDS, FINAL_SEEDS ниже.

Миры («истина» относительно движка): calibrated — истинные параметры = параметры банка; misspec — трудность семейств
сдвинута N(0; 0,5), наклоны × lognormal(0; 0,25); amult — истинный наклон = наклон движка × m (чувствительность к
допущению об a, m = 0,7 / 1,4); testlet — части многошаговых заданий зависимы (общий сдвиг N(0; 0,5) на задание);
fatigue — усталость: θ к концу 30 заданий ниже на 0,3. «Стандартные условия» (--bank-a): наклоны банка заменены
допущением аналогичных решений и в движке, и в «истине» (строка рядом с консервативной, не вместо неё).

Популяция — как в независимой модели аудита (docs/audit_2010/scripts/sim.py): θ ~ N(0; 1,3), заявленный грейд =
истинный + {0, 0, 0, +1, +1, −1}; направление — равновероятно; стек — 1–3 тега направления (∝ числу семейств).

Запуск (из backend/), шард по зёрнам и сведение:
    python -m app.modules.validation.product_sim --phase final --world calibrated --n 3000 --retest --fixed \\
        --expect-bank-hash <хэш> --out /tmp/f.json
    python -m app.modules.validation.product_sim merge --out data/product_sim_final_calibrated.json /tmp/f_*.json
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import datetime as dt
import gzip
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

# Профиль стенда fsp-draft.ru: /opt/spectrek_fsp/app/.env на 21.10.2026 + поправка №2 (значения по умолчанию
# app/core/config.py: ASSESSMENT_VERDICT_RULE=sprt, SPRT δ/α/β, продление 30 / 90, выбор по 3PL на минуту, угадывание по
# варианту). Подставляются до импорта приложения, если не заданы в окружении.
STAND_ENV = {
    "ASSESSMENT_CONFIRM_LEVEL": "0.8",
    "ASSESSMENT_MAX_ITEMS": "20",
    "ASSESSMENT_TWO_STAGE_CONFIRM": "0.5",
    "ASSESSMENT_CODE_QUOTA_EXT": "true",
    "ASSESSMENT_GUESSING_3PL": "true",
    "GRADES_EXT_ENABLED": "true",
    "ASSESSMENT_TWO_STAGE_ENABLED": "true",
    "GRADES_EXT_REFINE_ITEMS": "10",
    "GRADES_EXT_REFINE_MINUTES": "25",
    "CATALOG_EXT_ENABLED": "1",
    "LLM_DISABLED": "true",
    "ASSESSMENT_AI_MARK": "false",
}

TRAIN_SEEDS = tuple(range(1101, 1111))   # подбор настроек
TEST_SEEDS = tuple(range(2201, 2211))    # отчёт прежней механики (T1–T3 на 603474f — запасной набор)
# Итоговый прогон на замороженном банке стенда: новые зёрна, один прогон, хэш банка — в коммит до прогона.
FINAL_SEEDS = tuple(range(4401, 4411))
# «Стандартные условия» (S-T, протокол А15, решение штаба 21.10): свои зёрна, один прогон, публикуется при любом исходе
ST_SEEDS = tuple(range(5501, 5511))
ST_THETA_SD = 0.25  # θ ~ N(центр ступени; 0,25), истинный грейд равновероятен Intern…Lead
THETA_SD = 1.3
CLAIM_SHIFT = (0, 0, 0, 1, 1, -1)
ORDER_ALL = ("none", "intern", "junior", "middle", "senior", "lead", "principal")
CODE_OPEN = {"find_bug", "predict_output", "choose_fix", "open_answer", "open_book_3step", "incident_sim",
             "code_fill", "code_trace", "write_code"}
LONG = {"open_answer", "open_book_3step", "incident_sim"}
# Консервативная модель устной защиты (доп. этап после второго этапа, если решения всё ещё нет): ORAL_K вопросов у
# порога заявленного грейда, наклон ORAL_A, без угадывания — меньше информации, чем ORAL_K практических заданий банка
# (a = 1,3). Если и после неё решения нет — «не подтверждён: данных недостаточно» (без монетки).
ORAL_K = 5
ORAL_A = 1.0
TESTLET_SD = 0.5
FATIGUE_PER_ITEM = 0.01
DIST_BINS = (0.0, 0.25, 0.5, 1.0, 99.0)


def _rank(g: str | None) -> int:
    return ORDER_ALL.index(g) if g in ORDER_ALL else 0


def wilson(k: int, n: int, z: float = 1.959964) -> list[float] | None:
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def _git_commit() -> str | None:
    if os.environ.get("CODE_COMMIT"):  # копия без .git (под RunPod, «Москва») — коммит кода передаётся явно
        return os.environ["CODE_COMMIT"][:12]
    try:
        return subprocess.check_output(["git", "rev-parse", "--short=9", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


@dataclass
class World:
    seed: int
    kind: str = "calibrated"  # calibrated | misspec | amult | testlet | fatigue | st
    a_mult: float = 1.0

    def family_truth(self, fid: str) -> tuple[float, float]:
        """(множитель наклона, сдвиг трудности) семейства — постоянны в пределах мира."""
        if self.kind == "amult":
            return float(self.a_mult), 0.0
        if self.kind != "misspec":
            return 1.0, 0.0
        r = np.random.default_rng([self.seed, 2, zlib.crc32(fid.encode())])
        return float(r.lognormal(0.0, 0.25)), float(r.normal(0.0, 0.5))


def apply_bank_a(spec: str) -> dict:
    """«Стандартные условия»: наклоны банка заменяются допущением (в движке и, значит, в «истине» calibrated).
    spec — «mcq=1.8,code=1.8»: mcq — части с выбором варианта (вопрос с выбором, выбор исправления, шаги 1–2
    многошаговых), code — остальные части. Меняются массивы a кэшированного пула движка (на время процесса)."""
    from app.modules.assessment import bank_engine as be
    from app.modules.assessment.sprt import OPTION_STEPS

    vals = dict(kv.split("=") for kv in spec.split(",") if "=" in kv)
    am, ac = float(vals.get("mcq", 0) or 0), float(vals.get("code", 0) or 0)
    from app.core.config import get_settings

    for n_sub in {1, max(1, get_settings().assessment_subpools)}:
        for it in be._pool(n_sub):
            a = np.asarray(it.a, dtype=float).copy()
            steps = OPTION_STEPS.get(it.format, ())
            opt_idx = set(range(len(a))) if steps is None else {j for j in steps if j < len(a)}
            for j in range(len(a)):
                if j in opt_idx and am:
                    a[j] = am
                elif j not in opt_idx and ac:
                    a[j] = ac
            object.__setattr__(it, "a", a) if hasattr(it, "__dataclass_fields__") else setattr(it, "a", a)
    return {"mcq": am or None, "code": ac or None}


class Sim:
    def __init__(self, world: World, rater_noise: float = 0.0, guessing: bool = True, population: str = "hard"):
        from app.modules.assessment import bank_engine as be
        from app.modules.assessment import sprt as sp
        from app.modules.assessment import two_stage
        from app.modules.assessment.bank_engine import BankEngine
        from app.modules.catalog import levels

        self.be, self.sp, self.two_stage, self.levels = be, sp, two_stage, levels
        self.world = world
        self.rater_noise = float(rater_noise)
        self.guessing = bool(guessing) and world.kind != "st"  # S-T: 2PL без угадывания
        self.population = population
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
        from assessment_bank import load_specs
        from app.modules.assessment.skill_map import stack_gate

        self.stack_tags: dict[str, Counter] = defaultdict(Counter)
        for spc in load_specs().values():
            if not spc.canary:
                for t in stack_gate(spc.direction, spc.skills):
                    self.stack_tags[spc.direction][t] += 1
        self.r_pop = np.random.default_rng([world.seed, 1])
        self.r_eng = np.random.default_rng([world.seed, 3])
        self.r_resp = np.random.default_rng([world.seed, 4])
        self.r_fix = np.random.default_rng([world.seed, 5])

    # -- кандидат
    def person(self) -> dict:
        d = self.directions[int(self.r_pop.integers(len(self.directions)))]
        order = ("none",) + tuple(self.levels.available_grades(d))
        from app.modules.catalog.seed_data import ALL_GRADE_CUTS

        if self.population.startswith("st"):
            # S-T: истинная ступень равновероятна Intern…Lead, θ ~ N(центр ступени; 0,25); заявки: st-a — честные,
            # st-b — треть завышает на ступень
            ladder = [g for g in order[1:] if g != "principal"]
            g0 = ladder[int(self.r_pop.integers(len(ladder)))]
            i0 = order.index(g0)
            hi = ALL_GRADE_CUTS[order[i0 + 1]] if i0 + 1 < len(order) else ALL_GRADE_CUTS[g0] + 1.0
            theta = float(self.r_pop.normal((ALL_GRADE_CUTS[g0] + hi) / 2.0, ST_THETA_SD))
        else:
            theta = float(self.r_pop.normal(0.0, THETA_SD))
        g = "none"
        for gr in order[1:]:
            if theta >= ALL_GRADE_CUTS[gr]:
                g = gr
        gi = order.index(g)
        if self.population == "st-a":
            shift = 0
        elif self.population == "st-b":
            shift = 1 if self.r_pop.random() < 1.0 / 3.0 else 0
        else:
            shift = CLAIM_SHIFT[int(self.r_pop.integers(len(CLAIM_SHIFT)))]
        ci = int(np.clip(gi + shift, 1, len(order) - 1))
        tags = self.stack_tags.get(d) or Counter()
        stack: list[str] = []
        if tags:
            names = sorted(tags)
            w = np.array([tags[t] for t in names], dtype=float)
            k = min(len(names), int(self.r_pop.integers(1, 4)))
            stack = [str(t) for t in self.r_pop.choice(names, size=k, replace=False, p=w / w.sum())]
        cuts = [ALL_GRADE_CUTS[gr] for gr in order[1:]]
        return {"direction": d, "theta": theta, "true_grade": g, "claim": order[ci], "order": order,
                "tau": float(self.r_pop.normal(0.0, 0.25)), "stack": stack,
                "cut_claim": float(ALL_GRADE_CUTS[order[ci]]),
                "dist_nearest": float(min(abs(theta - c) for c in cuts))}

    # -- ответы «истины»
    def _respond(self, cur: dict, theta_eff: float, snap: dict) -> np.ndarray:
        am, bs = self.world.family_truth(cur["family_id"])
        a = np.asarray(snap["a"], dtype=float) * am
        b = np.asarray(snap["b"], dtype=float) + bs + self.r_resp.normal(0.0, np.asarray(snap["sigma"], dtype=float))
        z = a * (theta_eff - b)
        if self.world.kind == "testlet" and len(b) > 1:
            z = z + a * self.r_resp.normal(0.0, TESTLET_SD)  # общий сдвиг на все части задания
        pr = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        if self.guessing:  # люди угадывают: в части с выбором варианта c = 1/K (K — число вариантов этого шага)
            c = np.zeros(len(pr))
            for j in range(len(pr)):
                kind = self.be.BankEngine._answer_kind(cur, j + 1)
                if kind == "option":
                    opts = self.be.BankEngine._step_options(cur, j + 1) or []
                    c[j] = 1.0 / max(2, len(opts)) if opts else 0.0
                elif kind == "line":
                    c[j] = 1.0 / max(2, int(cur["public"].get("code_lines") or 10))
            pr = c + (1.0 - c) * pr
        x = (self.r_resp.random(len(pr)) < pr).astype(float)
        if self.rater_noise > 0:
            for j in self.be.BankEngine.text_parts(cur):
                if j - 1 < len(x) and self.r_resp.random() < self.rater_noise:
                    x[j - 1] = 1.0 - x[j - 1]
        return x

    def run_session(self, st: dict, p: dict, pos0: int = 0) -> None:
        e = self.e
        pos = pos0
        while True:
            it = e.next_item(st)
            if it is None:
                break
            cur = e._current(st)
            snap = cur["pool"]
            th = p["theta"] - (FATIGUE_PER_ITEM * pos if self.world.kind == "fatigue" else 0.0)
            x = self._respond(cur, th, snap)
            t = float(np.exp(self.r_resp.normal(float(snap["beta_time"]) - p["tau"], 1.0 / float(snap["alpha_time"]))))
            t = max(5.0, min(t, float(cur["time_limit_s"])))
            cur["x"] = [float(v) for v in x]
            cur["done"], cur["time_s"], cur["log_t"], cur["overtime"] = True, t, math.log(t), False
            st["current"] = None
            if not cur.get("canary"):
                pos += 1

    def _seed(self) -> int:
        return int(self.r_eng.integers(1, 2**31 - 1))

    # -- путь кандидата в продукте: полный тест → (второй этап у порога) → (устная защита) → итог
    def flow(self, p: dict, *, previous_subpools=None, seen=None, seen_seeds=None, two_stage_on: bool = True,
             oral_on: bool = True) -> dict:
        e, ts_mod, sp = self.e, self.two_stage, self.sp
        st = e.start(direction=p["direction"], claimed_grade=p["claim"], stack_tags=p["stack"], seed=self._seed(),
                     previous_subpools=previous_subpools or [], previous_families=[],
                     seen=seen or {}, seen_seeds=seen_seeds or {})
        self.run_session(st, p)
        res = e.finish(st)
        det = res.details or {}
        v = det.get("verdict") or {}
        gba = det.get("grade_by_answers") or {}
        er = {"confirmed": res.confirmed, "provisional": res.provisional, "theta": res.theta, "se": res.se,
              "details": {"grade_by_answers": gba, "verdict": v}}
        ts = SimpleNamespace(status=_finished(), claimed_grade_id=p["claim"], direction_id=p["direction"],
                             result={"engine": e.name, "engine_result": er, "state": st, "mode": "full"})
        done = [i for i in st["items"] if i.get("done") and not i.get("canary")]
        soft_n = int(st["cfg"].get("sprt", {}).get("soft_max_items", st["cfg"]["max_items"]))
        soft_t = float(st["cfg"].get("sprt", {}).get("soft_max_time_s", st["cfg"]["max_time_s"]))
        min_main = sum(float(i.get("time_s") or 0) for i in done) / 60.0
        out = {"verdict_main": v.get("status"), "oral_main": bool((v.get("followup") or {}).get("oral_defense_required")),
               "grade_main": gba.get("product_grade") or ts_mod.session_grade(ts),
               "point_main": gba.get("point_grade"), "theta_wle_main": gba.get("theta_wle"), "se_wle_main": gba.get("se_wle"),
               "llr_main": v.get("llr"), "theta": res.theta, "se": res.se, "n_main": len(done),
               "code_open_main": sum(1 for i in done if i["format"] in CODE_OPEN),
               "min_main": min_main, "extended": bool(len(done) > soft_n or min_main * 60.0 > soft_t + 1e-6),
               "stop": det.get("stop_reason"), "integrity_level": (det.get("integrity") or {}).get("level"),
               "refined": False, "min_refine": 0.0, "n_refine": 0, "oral": False, "subpool": st.get("subpool"),
               "families": [i["family_id"] for i in st["items"] if not i.get("canary")],
               "seeds": {i["family_id"]: i["seed"] for i in st["items"] if not i.get("canary")}}
        status_now, llr_now, gba_now, st_last = out["verdict_main"], float(v.get("llr") or 0.0), gba, [st]
        tp = ts_mod.params()
        b = ts_mod.session_boundary(ts, tp) if (two_stage_on and tp["enabled"]) else None
        out["boundary"] = b.as_dict() if b is not None else None
        if b is not None:
            p2 = ts_mod.ext_params(tp, b.cut_grade)
            prev = dict(st, final_theta=res.theta, final_se=res.se)
            seen2 = dict(seen or {})
            for f in out["families"]:
                seen2.setdefault(f, 0)
            seeds2 = {k: list(vv) for k, vv in (seen_seeds or {}).items()}
            for f, s in out["seeds"].items():
                seeds2.setdefault(f, []).append(int(s))
            st2 = e.start(direction=p["direction"], claimed_grade=p["claim"], stack_tags=p["stack"], seed=self._seed(),
                          refine_from=prev, seen=seen2, seen_seeds=seeds2,
                          refine={**b.as_dict(), "level": p2["level"], "items": int(p2["items"]),
                                  "minutes": int(p2["minutes"]), "confirm": p2["confirm"],
                                  "confirm_up": p2["confirm_up"], "floor": p2["floor"], "source_session_id": "sim"})
            self.run_session(st2, p, pos0=len(done))
            res2 = e.finish(st2)
            det2 = res2.details or {}
            v2 = det2.get("verdict") or {}
            new = [i for i in st2["items"] if i.get("done") and not i.get("canary")]
            out.update(refined=True, n_refine=len(new), min_refine=sum(float(i.get("time_s") or 0) for i in new) / 60.0,
                       verdict_refine=v2.get("status"),
                       oral_refine=bool((v2.get("followup") or {}).get("oral_defense_required")),
                       families=out["families"] + [i["family_id"] for i in new])
            for i in new:
                out["seeds"][i["family_id"]] = i["seed"]
            status_now, llr_now = v2.get("status"), float(v2.get("llr") or 0.0)
            gba_now = det2.get("grade_by_answers") or gba_now
            st_last.append(st2)
        out["grade_stage2"] = gba_now.get("product_grade")
        out["verdict_stage2"] = status_now
        order = tuple(p["order"][1:])
        if status_now == "needs_followup" and oral_on and self.sp.sprt_on():
            # консервативная модель устной защиты: ORAL_K вопросов у порога, a = ORAL_A, без угадывания
            cut = p["cut_claim"]
            xo = (self.r_resp.random(ORAL_K) < 1.0 / (1.0 + np.exp(-ORAL_A * (p["theta"] - cut)))).astype(float)
            vp = sp.verdict_params()
            llr_o = sp.llr3(xo, [ORAL_A] * ORAL_K, [cut] * ORAL_K, [0.0] * ORAL_K, cut, vp["delta"])
            status_o = sp.sprt_status(llr_now + llr_o, vp["alpha"], vp["beta"])
            if vp["point_estimator"] == "wle":
                X, A, B, C = self._responses(st_last)
                th_p, _ = sp.wle(X + list(xo), A + [ORAL_A] * ORAL_K, B + [cut] * ORAL_K, C + [0.0] * ORAL_K)
                point = sp.point_grade(th_p, order)
            else:  # оценка уровня движка (EAP) — устная защита в неё не входит (консервативно)
                point = gba_now.get("point_grade") or "none"
            out.update(oral=True, verdict_oral=status_o)
            # решения нет и после устной защиты — «не подтверждён: данных недостаточно»; уровень по ответам — как есть
            status_final = status_o if status_o != "needs_followup" else "undecided"
            out["grade_final"] = sp.product_grade(status_o, point, p["claim"], order, upgrade=vp["upgrade_rule"],
                                                  next_up=bool(gba_now.get("next_up")))
        else:
            status_final = status_now if status_now != "needs_followup" else "undecided"
            out["grade_final"] = gba_now.get("product_grade") or out["grade_main"]
        out["verdict_final"] = status_final
        out["confirmed_final"] = status_final == "confirmed"
        return out

    def _responses(self, states: list[dict]) -> tuple[list, list, list, list]:
        """(x, a_eff, b, c) по частям всех выполненных заданий (как в движке) — для WLE после устной защиты."""
        from app.modules.assessment.bank_engine import _pool_from_snapshot
        from app.modules.assessment.sprt import public_guess

        X, A, B, C = [], [], [], []
        seen_tok = set()
        for st in states:
            for it in (st.get("prior") or []) + st["items"]:
                if not it.get("done") or it.get("canary") or it.get("token") in seen_tok:
                    continue
                seen_tok.add(it.get("token"))
                pi = _pool_from_snapshot(it["pool"])
                xs = [float(v) for v in it["x"]]
                cc = public_guess(it["format"], len(xs), it.get("public"), actual=True)
                X += xs
                A += list(np.asarray(pi.a_eff, dtype=float)[:len(xs)])
                B += list(np.asarray(pi.b, dtype=float)[:len(xs)])
                C += list(cc[:len(xs)])
        return X, A, B, C

    # -- базовая линия: фиксированная форма той же длины на том же кандидате (без адаптивности и без продления)
    def fixed(self, p: dict, length: int) -> dict:
        from app.core.config import get_settings
        from app.modules.assessment.bank_engine import _pool, stack_excluded
        from app.modules.assessment.exposure import family_guess
        from app.modules.assessment.intern_pool import intern_exclusions
        from app.modules.assessment.sprt import CODE_OPEN_FORMATS

        sp = self.sp
        pool = [i for i in _pool(max(1, get_settings().assessment_subpools))
                if not i.canary and i.block in ("common", p["direction"])]
        excl = set(stack_excluded(p["stack"]))
        if p["claim"] == "intern":
            excl.update(intern_exclusions(pool, p["direction"]))
        # форма заявленного грейда: семейства, у которых он в целевых грейдах (как у бумажного теста на этот грейд);
        # мало — добираем остальными; квота ≥ 1/3 практических, не больше 2 длинных
        pool = [i for i in pool if i.family_id not in excl]
        own = [i for i in pool if p["claim"] in i.grades]
        rest = [i for i in pool if p["claim"] not in i.grades]
        order_idx = list(self.r_fix.permutation(len(own))) + [len(own) + j for j in self.r_fix.permutation(len(rest))]
        allp = own + rest
        n_code = math.ceil(length / 3)
        take, n_long, n_co = [], 0, 0
        for want_code in (True, False):
            for k in order_idx:
                it = allp[k]
                if len(take) >= length or it in take:
                    continue
                is_code = it.format in CODE_OPEN_FORMATS
                if want_code and (not is_code or n_co >= n_code):
                    continue
                if it.format in LONG and n_long >= 2:
                    continue
                take.append(it)
                n_long += it.format in LONG
                n_co += is_code
        X, A, B, C = [], [], [], []
        vp = sp.verdict_params()
        llr = 0.0
        for pos, it in enumerate(take):
            am, bs = self.world.family_truth(it.family_id)
            a = np.asarray(it.a, dtype=float) * am
            b = np.asarray(it.b, dtype=float) + bs + self.r_fix.normal(0.0, np.asarray(it.sigma, dtype=float))
            c = family_guess(it.family_id, it.format, len(b))
            th = p["theta"] - (FATIGUE_PER_ITEM * pos if self.world.kind == "fatigue" else 0.0)
            pr = c + (1 - c) / (1 + np.exp(-np.clip(a * (th - b), -30, 30)))
            x = (self.r_fix.random(len(pr)) < pr).astype(float)
            llr += sp.llr3(x, it.a_eff, it.b, c, p["cut_claim"], vp["delta"])
            X += list(x)
            A += list(np.asarray(it.a_eff, dtype=float))
            B += list(np.asarray(it.b, dtype=float))
            C += list(c)
        status = sp.sprt_status(llr, vp["alpha"], vp["beta"])
        th_w, _ = sp.wle(X, A, B, C)
        point = sp.point_grade(th_w, tuple(p["order"][1:]))
        return {"fixed_n": len(take), "fixed_verdict": status,
                "fixed_grade": sp.product_grade(status, point, p["claim"], tuple(p["order"][1:]))}


def _finished():
    from app.core.enums import TestSessionStatus

    return TestSessionStatus.finished


# ---------------------------------------------------------------- метрики

def frac(k: int, m: int) -> dict:
    return {"k": int(k), "n": int(m), "value": round(k / m, 4) if m else None, "ci95": wilson(int(k), int(m))}


def _truth_ok(r: dict) -> bool:
    return _rank(r["true_grade"]) >= _rank(r["claim"])


def _dist_bin(d: float) -> str:
    for lo, hi in zip(DIST_BINS[:-1], DIST_BINS[1:]):
        if lo <= d < hi:
            return f"{lo:g}–{hi:g}" if hi < 90 else f"≥ {lo:g}"
    return "?"


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    ok = [r for r in rows if _truth_ok(r)]
    over = [r for r in rows if not _truth_ok(r)]
    dec_main = [r for r in rows if r["verdict_main"] in ("confirmed", "not_confirmed")]
    dec_ok = sum(1 for r in dec_main if (r["verdict_main"] == "confirmed") == _truth_ok(r))
    fc_main = sum(1 for r in over if r["verdict_main"] == "confirmed")
    dec_final = [r for r in rows if r["verdict_final"] in ("confirmed", "not_confirmed")]
    dec_final_ok = sum(1 for r in dec_final if (r["verdict_final"] == "confirmed") == _truth_ok(r))
    acc = sum(1 for r in rows if r["confirmed_final"] == _truth_ok(r))
    fc = sum(1 for r in over if r["confirmed_final"])
    fr = sum(1 for r in ok if not r["confirmed_final"])
    st2 = [r for r in rows if r["verdict_stage2"] in ("confirmed", "not_confirmed")]

    def ex(key: str, rs: list[dict]) -> int:
        return sum(1 for r in rs if r[key] == r["true_grade"])

    def w1(key: str, rs: list[dict]) -> int:
        return sum(1 for r in rs if abs(_rank(r[key]) - _rank(r["true_grade"])) <= 1)

    not_under = [r for r in rows if _rank(r["true_grade"]) <= _rank(r["claim"])]
    mins_main = np.array([r["min_main"] for r in rows])
    mins_total = np.array([r["min_main"] + r["min_refine"] for r in rows])
    refined = [r for r in rows if r["refined"]]
    items = np.array([r["n_main"] for r in rows])
    co = np.array([r["code_open_main"] / max(1, r["n_main"]) for r in rows])
    out = {
        "n": n, "n_overclaim": len(over), "n_true_ok": len(ok),
        # после основной части (одна сессия с продлением у спорного порога)
        "confident_share_main": frac(len(dec_main), n),
        "confident_accuracy_main": frac(dec_ok, len(dec_main)),
        "false_confirm_main_all": frac(fc_main, n),
        "false_confirm_main_among_overclaim": frac(fc_main, len(over)),
        "exact_grade_main": frac(ex("grade_main", rows), n),
        "within_one_main": frac(w1("grade_main", rows), n),
        # после второго этапа (до устной защиты)
        "confident_share_stage2": frac(len(st2), n),
        # итог продукта (после второго этапа и устной защиты; без решения — «не подтверждён: данных недостаточно»)
        "verdict_accuracy_final": frac(acc, n),
        "confident_share_final": frac(len(dec_final), n),
        "confident_accuracy_final": frac(dec_final_ok, len(dec_final)),
        "false_confirm_all": frac(fc, n),
        "false_confirm_among_overclaim": frac(fc, len(over)),
        "false_reject_among_true": frac(fr, len(ok)),
        "undecided_final": frac(sum(1 for r in rows if r["verdict_final"] == "undecided"), n),
        "exact_grade_final": frac(ex("grade_final", rows), n),
        "exact_grade_final_not_underclaim": frac(ex("grade_final", not_under), len(not_under)),
        "within_one_final": frac(w1("grade_final", rows), n),
        "gross_error_2plus": frac(sum(1 for r in rows if abs(_rank(r["grade_final"]) - _rank(r["true_grade"])) >= 2), n),
        "followup_share": frac(len(refined), n),
        "oral_share": frac(sum(1 for r in rows if r.get("oral")), n),
        "extended_share": frac(sum(1 for r in rows if r.get("extended")), n),
        "integrity_low_share_honest": frac(sum(1 for r in rows if r.get("integrity_level") == "low"), n),
        "minutes_main": {"mean": round(float(mins_main.mean()), 1), "p90": round(float(np.percentile(mins_main, 90)), 1)},
        "minutes_total": {"mean": round(float(mins_total.mean()), 1), "p90": round(float(np.percentile(mins_total, 90)), 1)},
        "minutes_refine_among_refined": round(float(np.mean([r["min_refine"] for r in refined])), 1) if refined else None,
        "items_main": {"mean": round(float(items.mean()), 1), "min": int(items.min()), "max": int(items.max())},
        "items_refine_among_refined": round(float(np.mean([r["n_refine"] for r in refined])), 1) if refined else None,
        "code_open_share_main": {"mean": round(float(co.mean()), 3),
                                 "share_sessions_ge_one_third": round(float(np.mean(co >= 1 / 3 - 1e-9)), 4)},
    }
    # вне зоны безразличия ±0,25 / ±0,4 у заявленного порога — рядом с полной популяцией
    for z in (0.25, 0.4):
        rs = [r for r in rows if abs(r["theta_true"] - r["cut_claim"]) >= z]
        o = [r for r in rs if not _truth_ok(r)]
        d = [r for r in rs if r["verdict_final"] in ("confirmed", "not_confirmed")]
        out[f"outside_{str(z).replace('.', '_')}"] = {
            "n": len(rs), "confident_accuracy_final": frac(sum(1 for r in d if (r["verdict_final"] == "confirmed") == _truth_ok(r)), len(d)),
            "false_confirm_all": frac(sum(1 for r in o if r["confirmed_final"]), len(rs)),
            "verdict_accuracy_final": frac(sum(1 for r in rs if r["confirmed_final"] == _truth_ok(r)), len(rs))}
    # у порога / вдали от порога (расстояние истинного θ до заявленного порога — вердикт; до ближайшего — грейд)
    by_d = defaultdict(list)
    by_dn = defaultdict(list)
    for r in rows:
        by_d[_dist_bin(abs(r["theta_true"] - r["cut_claim"]))].append(r)
        by_dn[_dist_bin(r["dist_nearest"])].append(r)
    out["by_distance_claim_cut"] = {k: {
        "n": len(v), "confident_share_main": frac(sum(1 for r in v if r["verdict_main"] in ("confirmed", "not_confirmed")), len(v)),
        "verdict_accuracy_final": frac(sum(1 for r in v if r["confirmed_final"] == _truth_ok(r)), len(v)),
        "false_confirm_all": frac(sum(1 for r in v if r["confirmed_final"] and not _truth_ok(r)), len(v))}
        for k, v in sorted(by_d.items())}
    out["by_distance_nearest_cut"] = {k: {"n": len(v), "exact_grade_final": frac(ex("grade_final", v), len(v)),
                                          "within_one_final": frac(w1("grade_final", v), len(v))}
                                      for k, v in sorted(by_dn.items())}
    # операционная характеристика: P(подтверждён | θ − порог) по корзинам 0,25 логита
    oc = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        k = math.floor((r["theta_true"] - r["cut_claim"]) / 0.25) * 0.25
        k = max(-2.0, min(2.0, k))
        oc[k][0] += 1
        oc[k][1] += r["confirmed_final"]
        oc[k][2] += r["verdict_main"] == "confirmed"
    out["oc_curve"] = [{"from": round(k, 2), "to": round(k + 0.25, 2), "n": v[0],
                        "p_confirmed_final": round(v[1] / v[0], 4), "p_confirmed_main": round(v[2] / v[0], 4)}
                       for k, v in sorted(oc.items())]
    fx = [r for r in rows if r.get("fixed_grade") is not None]
    if fx:
        fdec = [r for r in fx if r["fixed_verdict"] in ("confirmed", "not_confirmed")]
        out["fixed_vs_adaptive"] = {
            "what": "фиксированная форма той же длины (число заданий основной части адаптивного теста этого кандидата), "
                    "те же кандидаты, то же правило решения и оценка уровня, без адаптивности, продления и второго этапа",
            "n": len(fx),
            "adaptive_main": {"exact_grade": frac(ex("grade_main", fx), len(fx)), "within_one": frac(w1("grade_main", fx), len(fx)),
                              "confident_share": frac(sum(1 for r in fx if r["verdict_main"] in ("confirmed", "not_confirmed")), len(fx)),
                              "false_confirm_all": frac(sum(1 for r in fx if r["verdict_main"] == "confirmed" and not _truth_ok(r)), len(fx))},
            "fixed": {"exact_grade": frac(ex("fixed_grade", fx), len(fx)), "within_one": frac(w1("fixed_grade", fx), len(fx)),
                      "confident_share": frac(len(fdec), len(fx)),
                      "false_confirm_all": frac(sum(1 for r in fx if r["fixed_verdict"] == "confirmed" and not _truth_ok(r)), len(fx))},
        }
    return out


def by_claim(rows: list[dict]) -> dict:
    g = defaultdict(list)
    for r in rows:
        g[r["claim"]].append(r)
    keys = ("n", "verdict_accuracy_final", "false_confirm_all", "false_confirm_among_overclaim", "confident_share_main",
            "confident_accuracy_main", "exact_grade_final", "within_one_final", "minutes_total", "extended_share")
    return {k: {kk: summarize(g[k])[kk] for kk in keys} for k in ORDER_ALL[1:] if g.get(k)}


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


def retest_summary(pairs: list[dict]) -> dict:
    a = [_rank(x["g1"]) for x in pairs]
    b = [_rank(x["g2"]) for x in pairs]
    same = sum(1 for i, j in zip(a, b) if i == j)
    w1 = sum(1 for i, j in zip(a, b) if abs(i - j) <= 1)
    vsame = sum(1 for x in pairs if x["v1"] == x["v2"])
    return {"n_pairs": len(pairs), "kappa_w_quadratic": kappa_w(a, b, len(ORDER_ALL)),
            "exact_agreement": frac(same, len(a)), "within_one_agreement": frac(w1, len(a)),
            "verdict_agreement": frac(vsame, len(a)),
            "shared_families_mean": round(float(np.mean([x["shared"] for x in pairs])), 2) if pairs else None,
            "what": "тот же модельный кандидат проходит продукт второй раз: новые зёрна сессии, семейства первой попытки "
                    "исключены (как у повторной попытки в продукте); сравнивается итоговый уровень продукта"}


# ---------------------------------------------------------------- прогон

def run(phase: str, world: World, n: int, seeds: tuple[int, ...], rater_noise: float = 0.0, retest: bool = False,
        two_stage_on: bool = True, oral_on: bool = True, fixed: bool = False, progress: bool = True,
        population: str = "hard") -> dict:
    per_seed = max(1, n // len(seeds))
    rows: list[dict] = []
    pairs: list[dict] = []
    errors: list[str] = []
    t0 = time.time()
    for s in seeds:
        sim = Sim(World(s, world.kind, world.a_mult), rater_noise=rater_noise, population=population)
        for _ in range(per_seed):
            p = sim.person()
            try:
                o = sim.flow(p, two_stage_on=two_stage_on, oral_on=oral_on)
            except Exception as ex:  # сбой движка — это находка, а не шум: считаем и показываем
                errors.append(f"{type(ex).__name__}: {ex}"[:200])
                continue
            row = {"seed": s, "direction": p["direction"], "theta_true": round(p["theta"], 4),
                   "true_grade": p["true_grade"], "claim": p["claim"], "cut_claim": p["cut_claim"],
                   "dist_nearest": round(p["dist_nearest"], 4),
                   **{k: v for k, v in o.items() if k not in ("families", "seeds", "boundary")}}
            if fixed:
                try:
                    row.update(sim.fixed(p, o["n_main"]))
                except Exception as ex:
                    errors.append(f"fixed {type(ex).__name__}: {ex}"[:200])
            rows.append(row)
            if retest:
                seen = {f: 0 for f in o["families"]}
                seeds_ = {f: [int(v)] for f, v in o["seeds"].items()}
                try:
                    o2 = sim.flow(p, previous_subpools=[o["subpool"]] if o["subpool"] is not None else [],
                                  seen=seen, seen_seeds=seeds_, two_stage_on=two_stage_on, oral_on=oral_on)
                    pairs.append({"g1": o["grade_final"], "g2": o2["grade_final"], "v1": o["verdict_final"],
                                  "v2": o2["verdict_final"], "shared": len(set(o["families"]) & set(o2["families"]))})
                except Exception as ex:
                    errors.append(f"retest {type(ex).__name__}: {ex}"[:200])
            if progress and (len(rows) % 50 == 0):
                print(f"[{phase}/{world.kind}] {len(rows)}/{per_seed * len(seeds)} · {time.time() - t0:.0f} с",
                      file=sys.stderr, flush=True)
    return {"rows": rows, "pairs": pairs, "errors": errors, "elapsed_s": round(time.time() - t0, 1)}


def report(rows: list[dict], pairs: list[dict], errors: list[str]) -> dict:
    out = {"summary": summarize(rows), "by_claim": by_claim(rows),
           "claims": dict(Counter(r["claim"] for r in rows)), "true_grades": dict(Counter(r["true_grade"] for r in rows)),
           "engine_errors": {"n": len(errors), "examples": sorted(Counter(errors).items(), key=lambda kv: -kv[1])[:5]}}
    if pairs:
        out["retest"] = retest_summary(pairs)
    return out


def settings_snapshot() -> dict:
    from app.core.config import get_settings

    s = get_settings()
    keys = [k for k in type(s).model_fields if k.startswith(("assessment_", "grades_ext_"))]
    return {k: getattr(s, k) for k in sorted(keys)}


def check_final_bank(seeds: tuple[int, ...], expect_hash: str) -> None:
    """Итоговый прогон: только зёрна из FINAL_SEEDS и только на банке с хэшем, зафиксированным в коммите до прогона."""
    if not set(seeds) <= set(FINAL_SEEDS):
        raise SystemExit("итоговый прогон — только на FINAL_SEEDS")
    if not expect_hash:
        raise SystemExit("итоговый прогон: нужен --expect-bank-hash (хэш банка из коммита до прогона)")
    from app.modules.assessment.bank_engine import BankEngine

    got = (getattr(BankEngine(), "manifest", None) or {}).get("content_hash")
    if got != expect_hash:
        raise SystemExit(f"банк не тот: content_hash {got} ≠ ожидаемого {expect_hash}")


def _meta(a, seeds, world: World, bank_a: dict | None) -> dict:
    from app.modules.assessment.bank_engine import BankEngine

    e = BankEngine()
    return {
        "what": "симуляция продукта: движок стенда на реальном банке, модельные кандидаты (не люди)",
        "phase": a.phase, "world": world.kind, "a_mult": world.a_mult, "bank_a_override": bank_a, "seeds": list(seeds),
        "population_kind": a.population,
        "n_requested": a.n, "rater_noise_text_parts": a.rater_noise, "two_stage": not a.no_two_stage,
        "oral_model": None if a.no_oral else {"questions": ORAL_K, "a": ORAL_A, "guessing": 0.0,
                                              "what": "консервативная модель устной защиты после второго этапа"},
        "responses": "3PL с истинными параметрами: угадывание c = 1/K по фактическому числу вариантов шага, 1/строк для "
                     "выбора строки; разброс вариантов N(0; σ) по трудности",
        "population": ({"theta": f"N(0; {THETA_SD})", "claim_shift": list(CLAIM_SHIFT),
                        "stack": "1–3 тега направления, вероятность ∝ числу семейств банка с этим тегом"}
                       if a.population == "hard" else
                       {"theta": f"N(центр ступени; {ST_THETA_SD}), ступень равновероятна Intern…Lead",
                        "claims": "честные" if a.population == "st-a" else "треть завышает на ступень",
                        "stack": "1–3 тега направления, вероятность ∝ числу семейств банка с этим тегом"}),
        "bank": {"n_families": e.n_families, "manifest": getattr(e, "manifest", None)},
        "settings": settings_snapshot(), "git_commit": _git_commit(),
        "date": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "command": "cd backend && python -m app.modules.validation.product_sim " + " ".join(sys.argv[1:]),
    }


def merge(files: list[str], out: str) -> int:
    """Сведение шардов (по зёрнам) одного сценария: метрики пересчитываются по всем строкам."""
    parts = [json.loads(Path(f).read_text(encoding="utf-8")) for f in files]
    rows, pairs, errors = [], [], []
    for d in parts:
        raw = d.get("_raw") or {}
        rows += raw.get("rows") or []
        pairs += raw.get("pairs") or []
        errors += raw.get("errors") or []
    meta = dict(parts[0]["meta"])
    meta["seeds"] = sorted({s for d in parts for s in d["meta"]["seeds"]})
    meta["shards"] = [{"file": Path(f).name, "seeds": d["meta"]["seeds"], "git_commit": d["meta"].get("git_commit"),
                       "elapsed_s": d.get("elapsed_s")} for f, d in zip(files, parts)]
    meta["command_merge"] = "cd backend && python -m app.modules.validation.product_sim merge --out " + out + " " + \
        " ".join(Path(f).name for f in files)
    res = report(rows, pairs, errors)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps({"meta": meta, **res}, ensure_ascii=False, indent=1, default=str) + "\n",
                         encoding="utf-8")
    with gzip.open(str(out).replace(".json", ".rows.jsonl.gz"), "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    print(json.dumps({k: res["summary"].get(k) for k in ("n", "confident_accuracy_main", "confident_share_main",
                                                         "false_confirm_all", "exact_grade_final", "within_one_final")},
                     ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "merge":
        ap = argparse.ArgumentParser()
        ap.add_argument("--out", required=True)
        ap.add_argument("files", nargs="+")
        a = ap.parse_args(argv[1:])
        return merge(a.files, a.out)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--phase", choices=("train", "test", "final", "st"), required=True)
    ap.add_argument("--population", choices=("hard", "st-a", "st-b"), default="hard")
    ap.add_argument("--expect-bank-hash", type=str, default="",
                    help="для --phase final: content_hash банка из BANK_SYNC.json, зафиксированный в коммите до прогона")
    ap.add_argument("--world", choices=("calibrated", "misspec", "amult", "testlet", "fatigue", "st"), default="calibrated")
    ap.add_argument("--a-mult", type=float, default=1.0)
    ap.add_argument("--bank-a", type=str, default="", help="«стандартные условия»: mcq=…,code=… (движок и истина)")
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--rater-noise", type=float, default=0.0)
    ap.add_argument("--retest", action="store_true")
    ap.add_argument("--fixed", action="store_true", help="базовая линия: фиксированная форма той же длины")
    ap.add_argument("--no-two-stage", action="store_true")
    ap.add_argument("--no-oral", action="store_true")
    ap.add_argument("--seeds", type=str, default="")
    ap.add_argument("--out", type=str, required=True)
    a = ap.parse_args(argv)
    default_seeds = {"train": TRAIN_SEEDS, "test": TEST_SEEDS, "final": FINAL_SEEDS, "st": ST_SEEDS}[a.phase]
    seeds = tuple(int(x) for x in a.seeds.split(",")) if a.seeds else default_seeds
    if a.phase != "train" and set(seeds) & set(TRAIN_SEEDS):
        raise SystemExit("отчёт — не на зёрнах обучения")
    if a.phase == "final":
        check_final_bank(seeds, a.expect_bank_hash)
    if a.phase == "st":
        if not set(seeds) <= set(ST_SEEDS):
            raise SystemExit("стандартные условия — только на ST_SEEDS")
        check_final_bank(FINAL_SEEDS, a.expect_bank_hash)
    bank_a = apply_bank_a(a.bank_a) if a.bank_a else None
    world = World(0, a.world, a.a_mult)
    r = run(a.phase, world, a.n, seeds, rater_noise=a.rater_noise, retest=a.retest, two_stage_on=not a.no_two_stage,
            oral_on=not a.no_oral, fixed=a.fixed, population=a.population)
    res = report(r["rows"], r["pairs"], r["errors"])
    meta = _meta(a, seeds, world, bank_a)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"meta": meta, **res, "elapsed_s": r["elapsed_s"],
                                       "_raw": {"rows": r["rows"], "pairs": r["pairs"], "errors": r["errors"]}},
                                      ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: res["summary"].get(k) for k in ("n", "confident_accuracy_main", "confident_share_main",
                                                         "false_confirm_all", "exact_grade_final", "within_one_final",
                                                         "minutes_total")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    for k, v in STAND_ENV.items():
        os.environ.setdefault(k, v)
    raise SystemExit(main())
