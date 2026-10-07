"""Движок теста на пакете банка заданий ``assessment_bank`` (протокол AssessmentEngine из engine.py).

Сессия = общий блок + блок направления, адаптивный выбор семейства по максимуму информации
(``psychometrics.CATSession``: доля общего блока ≈ 40 %, канарейки на позициях 2, 6, 10). Классификация по
грейду: с 5-го задания информация считается в ближайшем неопределённом пороге грейда, основная часть (8–16
заданий, до 60 минут) заканчивается, когда ни один порог не попадает в θ̂ ± z·SE (z = 1,28 — 90 % с одной
стороны) или SE ≤ 0,35. Если после неё ближайший порог ещё внутри интервала — дотестирование до точности у
этого порога: до 6 коротких заданий (≤ 5 минут каждое, всего ≤ 20 минут) — сначала из своего субпула, затем из
остального банка направления, кроме семейств прошлой попытки и субпулов на карантине, — пока порог не выйдет
из интервала.
Итог: θ, SE, решение по грейду ``psychometrics.decide`` (без принудительного понижения), детектор предзнания
по канарейкам и времени ответов (``psychometrics.CanaryDetector``) с пересчётом θ без подозрительных ответов.

Безопасность:
* кандидату уходит только stem/код/варианты текущего шага; ключ, рубрика, семейство и seed остаются на
  сервере. item_id — случайный токен: по variant_id (family_id:seed) открытый генератор восстановил бы ключ;
* seed рабочих заданий берётся из криптостойкого ГСЧ в диапазоне ~2·10⁹ — заранее перебрать варианты
  нельзя, каждый кандидат получает свой вариант; канарейки — только из намеренно опубликованных seed;
* код кандидатов не исполняется: ответы сверяются с ключами, вывод программ — после нормализации
  ``metrics.normalize_output``; открытые ответы оценивает grader.grade_open (LLM по рубрике / «на проверке»).

Время показа и ответа фиксирует сервер (для каждого шага), клиентское время сохраняется рядом —
из серверного времени считается log T для модели времени детектора.

Состояние — JSON в test_sessions.result["state"]; CATSession пересобирается из него на каждом запросе
(детерминированно: ГСЧ выбора зависит от seed сессии и номера позиции). Пакет банка не изменяется.
"""
from __future__ import annotations

from functools import lru_cache
import json
import logging
import math
from pathlib import Path
import secrets
import time
from typing import Any

import numpy as np

import assessment_bank
from assessment_bank import generate, get_spec, load_specs
from assessment_bank.metrics import normalize_output
from assessment_bank.psychometrics import (CanaryDetector, CATConfig, CATSession, PoolItem, TimedResponse,
                                           pool_from_specs, prob)
from assessment_bank.registry import canary_published_seeds

from app.modules.assessment import integrity
from app.modules.assessment.engine import GRADES, AnswerFeedback, EngineResult, ItemPublic
from app.modules.assessment.exposure import AppCATSession, choose_subpool, exposure_control, parse_quarantine
from app.modules.assessment.grader import grade_open
from app.modules.assessment.grades import GRADE_RU, cuts_tuple, decide_grade, scale as platform_scale, start_theta
from app.modules.assessment.intern_pool import intern_exclusions
from app.modules.assessment.skill_map import to_stack_tags

log = logging.getLogger("assessment")

SEED_MIN, SEED_MAX = 10_000_000, 2**31 - 1
ANSWER_KIND = {"find_bug": "line", "predict_output": "text", "choose_fix": "option", "mcq_concept": "option",
               "open_answer": "text"}
MAX_TEXT = 20_000


def bank_manifest() -> dict:
    p = Path(assessment_bank.__file__).parent / "BANK_SYNC.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=4)
def _pool(n_subpools: int) -> tuple[PoolItem, ...]:
    return tuple(pool_from_specs(load_specs().values(), n_subpools=n_subpools))


def _pool_snapshot(pi: PoolItem) -> dict:
    return {"family_id": pi.family_id, "block": pi.block, "format": pi.format, "grades": list(pi.grades),
            "canary": pi.canary, "a": pi.a.tolist(), "b": pi.b.tolist(), "sigma": pi.sigma.tolist(),
            "time_limit_s": pi.time_limit_s, "beta_time": pi.beta_time, "alpha_time": pi.alpha_time,
            "subpool": pi.subpool}


def _pool_from_snapshot(d: dict) -> PoolItem:
    return PoolItem(d["family_id"], d["block"], d["format"], tuple(d["grades"]), d["canary"],
                    np.asarray(d["a"], dtype=float), np.asarray(d["b"], dtype=float),
                    np.asarray(d["sigma"], dtype=float), float(d["time_limit_s"]), float(d["beta_time"]),
                    float(d.get("alpha_time", 1.5)), int(d.get("subpool", 0)))


def _finite(obj: Any) -> Any:
    """NaN/inf → None: состояние и результат хранятся в JSON (PostgreSQL не принимает NaN)."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_finite(v) for v in obj]
    return obj


def _items_ru(n: int) -> str:
    n = int(n)
    word = "задание" if n % 10 == 1 and n % 100 != 11 else (
        "задания" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "заданий")
    return f"{n} коротк{'ое' if word == 'задание' else 'их'} {word}"


def _x_list(it: dict) -> list[float]:
    return [float("nan") if v is None else float(v) for v in it["x"]]


class BankEngine:
    def __init__(self) -> None:
        specs = load_specs()  # реестр семейств грузится сразу: ошибка — заметна при старте, а не на кандидате
        man = bank_manifest()
        self.manifest = {k: man.get(k) for k in ("commit", "dirty_files", "content_hash", "synced_at", "n_families")}
        self.version = (man.get("content_hash") or "dev")[:8]
        self.name = f"bank-{self.version}"
        self.n_families = len(specs)
        self.scale = platform_scale()  # пороги платформы: Стажёр, Junior, Middle, Senior

    # ------------------------------------------------------------------ настройки
    @staticmethod
    def _settings():
        from app.core.config import get_settings

        return get_settings()

    def _base_cfg(self) -> dict:
        s = self._settings()
        return {"min_items": s.assessment_min_items, "max_items": s.assessment_max_items,
                "se_target": s.assessment_se_target, "max_time_s": s.assessment_max_minutes * 60.0,
                "ext_items": s.assessment_extension_items, "ext_time_s": s.assessment_extension_minutes * 60.0,
                "stop_rule": s.assessment_stop_rule, "classify_z": s.assessment_classify_z,
                "select_at": s.assessment_select_at, "ext_own_first": s.assessment_extension_own_first,
                "subpools": max(1, s.assessment_subpools),
                "exposure": s.assessment_exposure,
                "max_per_format": {"open_book_3step": s.assessment_max_open_book, "open_answer": s.assessment_max_open_answer}}

    # ------------------------------------------------------------------ протокол
    def start(self, *, direction: str, claimed_grade: str, stack_tags: list[str], seed: int,
              previous_subpools: list[int] | None = None, previous_families: list[str] | None = None) -> dict:
        cfg = self._base_cfg()
        # Ротация субпулов: первая попытка — по seed сессии, повторная — другой субпул (параллельная форма);
        # субпулы на карантине (утечка) не выдаются. См. exposure.py.
        subpool = choose_subpool(cfg["subpools"], seed, previous_subpools,
                                 parse_quarantine(self._settings().assessment_subpool_quarantine))
        if claimed_grade == "intern":  # лёгких семейств мало — тест Стажёра идёт без ротации субпулов (intern_pool.py)
            subpool = None
        return {
            "engine": self.name, "bank": self.manifest, "direction": direction, "claimed_grade": claimed_grade,
            "seed": int(seed), "stack": stack_tags, "cfg": cfg, "subpool": subpool, "items": [], "skipped": [],
            # семейства прошлой попытки не попадают в дотестирование (оно берёт задания и из другого субпула)
            "exclude_ext": sorted(set(previous_families or [])),
            "current": None, "ext": None, "done": False, "stop_reason": None, "trace": [], "outbox": [],
            "started_at": time.time(),
        }

    def next_item(self, state: dict) -> ItemPublic | None:
        if state.get("done"):
            return None
        cur = self._current(state)
        if cur is not None:
            return self._public(state, cur)
        for _ in range(8):  # семейство с ошибкой генерации пропускается, выбирается следующее
            sess = self._rebuild(state)
            pi = self._select(state, sess)
            if pi is None:
                state["done"] = True
                state["theta"], state["se"] = round(sess.theta, 4), round(sess.se, 4)
                return None
            try:
                it = self._issue(state, pi, sess)
            except Exception as e:  # noqa: BLE001 — дефект конкретного семейства не должен ронять тест
                log.error("Банк: семейство %s не сгенерировалось: %s", pi.family_id, e)
                state["skipped"].append(pi.family_id)
                continue
            return self._public(state, it)
        state["done"], state["stop_reason"] = True, "generation_errors"
        return None

    def answer(self, state: dict, item_id: str, answer: Any, time_spent_ms: int | None = None,
               step: int | None = None, signals: dict | None = None) -> AnswerFeedback:
        it = self._current(state)
        n_done = sum(1 for i in state["items"] if i["done"])
        reject = AnswerFeedback(False, n_done, self._total_est(state), False)
        if it is None or it["token"] != item_id or state.get("done"):
            return reject
        k = self._current_step(it)
        if step is not None and int(step) != k:
            return reject
        kind = self._answer_kind(it, k)
        value = self._validate(it, k, kind, answer)
        if value is None:
            return reject
        now = time.time()
        prev = max([it["issued_at"]] + [a["at"] for a in it["answers"].values()])
        it["answers"][str(k)] = {"value": value, "at": now, "server_ms": int((now - prev) * 1000),
                                 "client_ms": time_spent_ms}
        sig = integrity.clean_signals(signals)
        if sig is not None:  # сигналы интерфейса (фокус, вставка) — копятся по шагам задания
            it["signals"] = integrity.merge_signals(it.get("signals"), sig)
        if k < it["parts"]:
            return AnswerFeedback(True, n_done, self._total_est(state), False)
        self._score(it)
        it["done"] = True
        it["time_s"] = round(max(1.0, now - it["issued_at"]), 3)
        it["log_t"] = round(math.log(it["time_s"]), 4)
        it["overtime"] = it["time_s"] > it["time_limit_s"] + 30
        state["current"] = None
        state["outbox"].append({"type": "answer", "token": it["token"]})
        return AnswerFeedback(True, n_done + 1, self._total_est(state), False)

    def finish(self, state: dict) -> EngineResult:
        claimed = state["claimed_grade"]
        # Повторная попытка оценить открытые ответы, которые не оценились при ответе (LLM был недоступен)
        for it in state["items"]:
            if it["done"] and any(v is None for v in it["x"]):
                self._score(it, retry=True)
        sess = self._rebuild(state)
        theta, se = float(sess.theta), float(sess.se)
        done = [i for i in state["items"] if i["done"]]
        lookup = sess.items
        clean, canary, clean_idx = [], [], []
        for k, it in enumerate(done):
            pi = lookup.get(it["family_id"])
            xs = [v for v in it["x"] if v is not None]
            if pi is None or not xs:
                continue
            p_exp = float(np.mean(prob(theta, pi.a_eff, pi.b)))
            tr = TimedResponse(float(np.mean(xs)), float(it["log_t"]), pi.beta_time, pi.alpha_time, p_exp)
            if it["canary"]:
                canary.append(tr)
            else:
                clean.append(tr)
                clean_idx.append(k)
        det = CanaryDetector().statistic(clean, canary)
        rescored, excluded = False, 0
        if det.flagged:
            mask = det.suspicious_mask(clean, det.tau_clean)
            excl = {clean_idx[i] for i, m in enumerate(mask) if m}
            if excl and len(excl) < len(clean_idx):
                theta, se = (float(v) for v in sess.rescore(excl))
                rescored, excluded = True, len(excl)
        dec = decide_grade(theta, se, claimed)

        scored = [i for i in done if not i["canary"]]
        pending = [i for i in scored if any(v is None for v in i["x"])]
        answered = [i for i in scored if any(v is not None for v in i["x"])]
        correct = sum(1 for i in answered if np.mean([v for v in i["x"] if v is not None]) >= 0.5)
        skills: dict[str, dict] = {}
        for it in answered:
            s = float(np.mean([v for v in it["x"] if v is not None]))
            for tag in it["skills"]:
                d = skills.setdefault(tag, {"correct": 0.0, "total": 0})
                d["total"] += 1
                d["correct"] += s
        for d in skills.values():
            d["score"] = round(d["correct"] / d["total"], 2) if d["total"] else 0.0
            d["correct"] = round(d["correct"], 2)
        ext = state.get("ext")
        pk = {"flagged": det.flagged, "combined": round(det.combined, 3), "excluded_answers": excluded}
        integ = integrity.assess([{
            "format": i["format"], "canary": i["canary"], "time_s": i.get("time_s"), "time_limit_s": i["time_limit_s"],
            "score": (float(np.mean([v for v in i["x"] if v is not None])) if any(v is not None for v in i["x"]) else None),
            "signals": i.get("signals"),
            "injection": any((g or {}).get("error") == "prompt_injection_suspected" for g in i.get("grading") or [])}
            for i in done], pk)
        details = {
            "bank": self.manifest, "n_families_in_bank": self.n_families,
            "stop_reason": state.get("stop_reason") or sess.stop_reason or "finished_early",
            "n_scored": len(scored), "n_canaries": sum(1 for i in done if i["canary"]),
            "time_used_s": round(sum(i.get("time_s", 0) for i in done), 1),
            "extension": ({"items": sum(1 for i in scored if i.get("ext")), "max_items": ext["n"],
                           "theta_before": ext["theta"], "se_before": ext["se"], "cut": ext["cut"]} if ext else None),
            "classification": {"stop_rule": state["cfg"].get("stop_rule", "se"),
                               "z": state["cfg"].get("classify_z", 1.0),
                               "grade_determined": not sess.uncertain_cuts(theta, se)},
            "pending_review": len(pending),
            "preknowledge": {"flagged": det.flagged, "combined": round(det.combined, 3),
                             "z_speed": round(det.z_speed, 3), "z_score": round(det.z_score, 3),
                             "n_canaries": det.n_canaries, "n_fast_correct": det.n_fast_correct,
                             "rescored": rescored, "excluded_answers": excluded},
            "overtime_items": sum(1 for i in done if i.get("overtime")),
            "integrity": integ,
            "subpool": state.get("subpool"), "exposure": state["cfg"].get("exposure"),
            "formats": {f: sum(1 for i in scored if i["format"] == f) for f in sorted({i["format"] for i in scored})},
            "category": f"{state['direction']}.{claimed}" if dec.confirmed else None,
            "assigned_grade": dec.assigned,
            "trace": [[round(t, 3), round(s_, 3)] for t, s_ in sess.trace],
            "grading": [{"format": i["format"], "parts": [g.get("method") if g else "auto" for g in i["grading"]],
                         "status": "pending" if any(v is None for v in i["x"]) else "scored"}
                        for i in scored if i["format"] in ("open_answer", "open_book_3step")],
        }
        retake = dec.retake_lower
        return EngineResult(
            engine=self.name, theta=round(theta, 3), se=round(se, 3), claimed_grade=claimed,
            point_grade=dec.point_grade, confirmed=dec.confirmed, upgrade_available=dec.upgrade_available,
            retake_lower=retake, probabilities=dec.probabilities, answered=len(answered), correct=correct,
            skills=skills, explanation=self._explain(dec, theta, se, claimed, details), details=_finite(details),
        )

    # ------------------------------------------------------------------ внутреннее
    @staticmethod
    def _current(state: dict) -> dict | None:
        tok = state.get("current")
        if not tok:
            return None
        return next((i for i in state["items"] if i["token"] == tok), None)

    def _cfg(self, state: dict) -> CATConfig:
        c = state["cfg"]
        ext = state.get("ext")
        # сессии, начатые до 06.10 (в cfg нет новых ключей), доигрываются по прежним правилам остановки и выбора
        return CATConfig(min_items=c["min_items"], max_items=c["max_items"], se_target=c["se_target"],
                         max_time_s=c["max_time_s"], cuts=cuts_tuple(), start_theta=start_theta(),
                         stop_rule=c.get("stop_rule", "se"), classify_z=float(c.get("classify_z", 1.0)),
                         select_at=c.get("select_at", "theta"),
                         ext_items=int(ext["n"]) if ext else int(c.get("ext_items", 0)),
                         ext_time_s=float(c.get("ext_time_s", 1800.0)),
                         ext_own_first=bool(c.get("ext_own_first", False)))

    def _rebuild(self, state: dict) -> CATSession:
        pool = list(_pool(state["cfg"].get("subpools", 1)))
        have = {p.family_id for p in pool}
        for it in state["items"]:
            if it["family_id"] not in have:  # семейство пропало из банка после выкладки — берём снимок параметров
                pool.append(_pool_from_snapshot(it["pool"]))
                have.add(it["family_id"])
        rng = np.random.default_rng([state["seed"], len(state["items"])])
        cfg = state["cfg"]
        expo = exposure_control(state["direction"]) if cfg.get("exposure", "none") == "sympson_hetter" else None
        # карантин читается на каждом запросе: субпул, выведенный из ротации посреди сессии, не попадёт и в дотестирование
        blocked = parse_quarantine(self._settings().assessment_subpool_quarantine)
        # Тест на Стажёра — только по лёгким семействам (сопоставление на стороне платформы, см. intern_pool.py);
        # исключённые семейства не попадают ни в основную часть, ни в дотестирование
        excl = intern_exclusions(pool, state["direction"]) if state["claimed_grade"] == "intern" else ()
        sess = AppCATSession(pool, state["direction"], self._cfg(state), expo, state["claimed_grade"],
                             state.get("subpool"), rng, max_per_format=cfg.get("max_per_format", {}),
                             exclude_ext=state.get("exclude_ext") or (), blocked_subpools=blocked, exclude=excl)
        lookup = sess.items
        for it in state["items"]:
            if it["done"] and it["family_id"] in lookup:
                sess.record(lookup[it["family_id"]], _x_list(it), it["log_t"], time_s=it["time_s"])
        for it in state["items"]:
            sess.used.add(it["family_id"])
        sess.used.update(state.get("skipped", []))
        ext = state.get("ext")
        if ext:
            sess.ext_start, sess.ext_cut = int(ext["start"]), ext.get("cut")
            sess.ext_reason_before = ext.get("reason_before", "")
        return sess

    def _select(self, state: dict, sess: CATSession) -> PoolItem | None:
        """Следующее семейство: основная часть, затем (если ближайший порог не определён) дотестирование у порога.
        Правила — в ``CATSession`` (общие с симуляцией /validation); здесь — только запись начала дотестирования."""
        nxt = sess.next_item()
        if sess.ext_start is not None and not state.get("ext"):
            claimed = state["claimed_grade"]
            state["ext"] = {"start": sess.ext_start, "n": sess.cfg.ext_items, "theta": round(sess.theta, 3),
                            "se": round(sess.se, 3), "cut": sess.ext_cut,
                            "p_claimed": round(self.scale.p_at_least(sess.theta, sess.se, claimed), 3),
                            "reason_before": sess.ext_reason_before}
        if nxt is None:
            state["stop_reason"] = sess.stop_reason
        return nxt

    def _issue(self, state: dict, pi: PoolItem, sess: CATSession) -> dict:
        spec = get_spec(pi.family_id)
        if spec.canary:
            pub = canary_published_seeds(pi.family_id)
            seed = int(pub[secrets.randbelow(len(pub))])
        else:
            seed = SEED_MIN + secrets.randbelow(SEED_MAX - SEED_MIN)
        v = generate(pi.family_id, seed)
        pv = v.public_view()
        steps = [s.model_dump() for s in (v.meta.steps or [])]
        it = {
            "token": secrets.token_urlsafe(9), "position": len(state["items"]) + 1, "family_id": pi.family_id,
            "seed": seed, "variant_id": v.variant_id, "format": spec.format, "block": pi.block,
            "canary": spec.canary, "skills": to_stack_tags(spec.direction, spec.skills), "bank_skills": spec.skills,
            "language": spec.language, "time_limit_s": spec.time_limit_s, "issued_at": time.time(),
            "ext": state.get("ext") is not None, "pool": _pool_snapshot(pi), "parts": spec.n_parts,
            "theta_before": round(float(sess.theta), 3),
            "public": {"stem": pv["stem"], "code": pv["code"], "options": pv["options"], "steps": steps,
                       "code_lines": len((pv["code"] or "").splitlines())},
            "key": v.answer_key.model_dump(include={"kind", "value", "accept"}),
            "rubric": v.rubric.model_dump() if v.rubric else None,
            "answers": {}, "x": [None] * spec.n_parts, "grading": [None] * spec.n_parts, "done": False,
        }
        state["items"].append(it)
        state["current"] = it["token"]
        state["outbox"].append({"type": "issue", "token": it["token"]})
        return it

    @staticmethod
    def _current_step(it: dict) -> int:
        for k in range(1, it["parts"] + 1):
            if str(k) not in it["answers"]:
                return k
        return it["parts"]

    @staticmethod
    def _answer_kind(it: dict, step: int) -> str:
        if it["format"] == "open_book_3step":
            return "text" if step == 3 else "option"
        return ANSWER_KIND.get(it["format"], "option")

    @staticmethod
    def _step_options(it: dict, step: int) -> list[dict] | None:
        opts = it["public"]["options"]
        if not opts:
            return None
        if it["format"] == "open_book_3step":
            return [{k: o[k] for k in ("id", "text", "code") if o.get(k) is not None}
                    for o in opts if o.get("step") == step] or None
        return [{k: o[k] for k in ("id", "text", "code") if o.get(k) is not None} for o in opts]

    def _validate(self, it: dict, step: int, kind: str, answer: Any) -> Any:
        if isinstance(answer, dict):
            answer = answer.get("value")
        if kind == "option":
            ids = {o["id"] for o in (self._step_options(it, step) or [])}
            a = str(answer).strip().upper() if answer is not None else ""
            return a if a in ids else None
        if kind == "line":
            try:
                n = int(str(answer).strip())
            except (TypeError, ValueError):
                return None
            return n if 1 <= n <= max(1, it["public"]["code_lines"]) else None
        if answer is None:
            answer = ""
        if not isinstance(answer, (str, int, float)):
            return None
        return str(answer)[:MAX_TEXT]

    def _score(self, it: dict, retry: bool = False) -> None:
        key = it["key"]
        fmt = it["format"]
        a = it["answers"]
        if fmt in ("choose_fix", "mcq_concept"):
            it["x"][0] = float(a["1"]["value"] == key["value"] or a["1"]["value"] in key.get("accept", []))
        elif fmt == "find_bug":
            v = a["1"]["value"]
            it["x"][0] = float(v == int(key["value"]) or str(v) in key.get("accept", []))
        elif fmt == "predict_output":
            got = normalize_output(a["1"]["value"])
            ok = got == normalize_output(str(key["value"])) or got in {normalize_output(x) for x in key.get("accept", [])}
            it["x"][0] = float(ok)
        elif fmt == "open_book_3step":
            for k in (1, 2):
                it["x"][k - 1] = float(a[str(k)]["value"] == key["value"].get(str(k)))
            if it["x"][2] is None:
                self._grade_text(it, 2, a["3"]["value"], it["public"]["steps"][2]["prompt"] if len(
                    it["public"]["steps"]) > 2 else None)
        elif fmt == "open_answer":
            if it["x"][0] is None:
                self._grade_text(it, 0, a["1"]["value"], None)

    def _grade_text(self, it: dict, part: int, text: str, step_prompt: str | None) -> None:
        g = grade_open(stem=it["public"]["stem"], code=it["public"]["code"], step_prompt=step_prompt,
                       rubric=it["rubric"], answer=text)
        prev = it["grading"][part] or {}
        g_d = g.to_dict()
        g_d["attempts"] = int(prev.get("attempts", 0)) + 1
        it["grading"][part] = g_d
        it["x"][part] = g.score if g.status == "scored" else None

    # ------------------------------------------------------------------ экспертная проверка открытых ответов
    @staticmethod
    def text_parts(it: dict) -> list[int]:
        """Индексы частей задания с развёрнутым ответом (оцениваются по рубрике)."""
        if it["format"] == "open_answer":
            return [0]
        if it["format"] == "open_book_3step":
            return [2]
        return []

    def review_items(self, state: dict) -> list[dict]:
        """Развёрнутые ответы сессии для экрана эксперта: задание, шаг, рубрика, ответ, статус и оценка LLM."""
        out = []
        for it in state.get("items", []):
            if not it.get("done"):
                continue
            for part in self.text_parts(it):
                ans = it["answers"].get(str(part + 1), {})
                g = it["grading"][part] or {}
                steps = it["public"].get("steps") or []
                out.append({
                    "token": it["token"], "part": part, "format": it["format"], "position": it["position"],
                    "stem": it["public"]["stem"], "code": it["public"]["code"], "code_language": it.get("language"),
                    "step_prompt": steps[part]["prompt"] if it["format"] == "open_book_3step" and len(steps) > part else None,
                    "rubric": it.get("rubric"), "answer": ans.get("value"), "skills": it.get("skills", []),
                    "status": "pending" if it["x"][part] is None else "scored",
                    "method": g.get("method") if it["x"][part] is not None else None,
                    "score": it["x"][part], "grading": g, "expert": g.get("expert") or it.get("expert_reviews", {}).get(str(part)),
                })
        return out

    def apply_review(self, state: dict, token: str, part: int, criteria: dict[str, float], comment: str | None,
                     reviewer: str) -> dict | None:
        """Оценка эксперта по критериям рубрики → балл части. Ответ «на проверке» получает балл эксперта;
        уже оцененный LLM — сохраняет балл LLM, а оценка эксперта пишется рядом (для расчёта согласия)."""
        it = next((i for i in state.get("items", []) if i["token"] == token and i.get("done")), None)
        if it is None or part not in self.text_parts(it):
            return None
        rub = it.get("rubric") or {}
        crit = {c["id"]: float(c.get("weight", 0)) for c in rub.get("criteria", [])}
        if not crit or set(criteria) != set(crit):
            return None
        vals = {k: min(1.0, max(0.0, float(v))) for k, v in criteria.items()}
        total_w = sum(crit.values()) or 1.0
        score = round(sum(crit[k] * vals[k] for k in crit) / total_w, 4)
        rec = {"criteria": vals, "score": score, "comment": (comment or "")[:2000], "reviewer": reviewer,
               "at": time.time()}
        it.setdefault("expert_reviews", {})[str(part)] = rec
        if it["x"][part] is None:  # «на проверке» → оценка эксперта входит в θ
            it["x"][part] = score
            prev = it["grading"][part] or {}
            it["grading"][part] = {**prev, "status": "scored", "method": "expert", "score": score,
                                   "criteria": vals, "comment": rec["comment"], "expert": rec}
            rec["applied"] = True
        else:
            g = it["grading"][part] or {}
            g["expert"] = rec
            it["grading"][part] = g
            rec["applied"] = False
            rec["llm_score"] = it["x"][part]
        state.setdefault("outbox", []).append({"type": "review", "token": token})
        return rec

    def _total_est(self, state: dict) -> int:
        c = state["cfg"]
        ext = state.get("ext")
        n_can = 3  # позиции канареек 2, 6, 10
        return c["max_items"] + n_can + (ext["n"] if ext else 0)

    def _public(self, state: dict, it: dict) -> ItemPublic:
        k = self._current_step(it)
        steps = it["public"]["steps"]
        is_ob3 = it["format"] == "open_book_3step"
        c = state["cfg"]
        return ItemPublic(
            item_id=it["token"], position=it["position"], total=self._total_est(state), format=it["format"],
            stem=it["public"]["stem"], options=self._step_options(it, k), code=it["public"]["code"],
            code_language=it["language"], time_limit_s=int(it["time_limit_s"]), skills=it["skills"],
            answer_kind=self._answer_kind(it, k), step=k if is_ob3 else None, steps_total=3 if is_ob3 else None,
            step_prompt=(steps[k - 1]["prompt"] if is_ob3 and len(steps) >= k else None),
            elapsed_s=int(max(0, time.time() - it["issued_at"])), block="common" if it["block"] == "common" else "direction",
            adaptive=True, min_items=c["min_items"], max_items=c["max_items"],
            answered=sum(1 for i in state["items"] if i["done"]), extension=bool(it.get("ext")),
        )

    @staticmethod
    def _explain(dec, theta: float, se: float, claimed: str, details: dict) -> str:
        g = GRADE_RU[claimed]
        p = sum(v for k, v in dec.probabilities.items() if GRADES.index(claimed) <= (
            GRADES.index(k) if k in GRADES else -1))
        ps = "более 99 %" if p > 0.99 else ("менее 1 %" if p < 0.01 else f"{p * 100:.0f} %")
        if dec.confirmed:
            s = f"Грейд {g} подтверждён: θ = {theta:+.2f} ± {se:.2f}, вероятность уровня не ниже {g} — {ps}."
            if dec.upgrade_available:
                s += f" Результат уверенно выше порога — можно пройти тест на {GRADE_RU[GRADES[GRADES.index(claimed) + 1]]}."
        else:
            s = (f"Грейд {g} пока не подтверждён: θ = {theta:+.2f} ± {se:.2f}, вероятность уровня не ниже {g} — "
                 f"{ps} (нужно ≥ 80 %). Принудительного понижения нет")
            s += (f": можно пройти тест на {GRADE_RU[dec.retake_lower]}." if dec.retake_lower else
                  ": можно повторить после подготовки." if GRADES.index(claimed) == 0 else
                  ": можно пройти тест на грейд ниже или повторить после подготовки.")
        ext = details.get("extension")
        if ext and ext.get("items"):
            s += f" Результат был у порога грейда — тест продлён на {_items_ru(ext['items'])} у этого порога."
        if details.get("pending_review"):
            s += (f" Открытых ответов на проверке: {details['pending_review']} — они пока не учтены, "
                  "результат предварительный.")
        if details["preknowledge"]["rescored"]:
            s += " Часть ответов исключена из оценки как аномально быстрые и верные (детектор утечек)."
        return s
