"""«Обмани тест» — настоящие боты-стратегии через движок продукта (BankEngine стенда, реальные варианты, реальная
проверка ответа `BankEngine.answer` → `_score`, второй этап у границы, итоговое решение), а не формулы.

Что считаем: `false_confirmed` — доля попыток, где продукт подтвердил заявленный грейд боту (итог после второго
этапа, если продукт его предложил: бот проходит его той же стратегией). Боты:
- random — случайный вариант / случайная строка кода / пустой вывод;
- position_A…D — всегда вариант на одной позиции (проверка баланса позиций ключа);
- longest, median_number, overlap — «решатель без знаний»: самый длинный вариант; вариант-середина числового ряда;
  вариант с наибольшим пересечением слов с условием и кодом;
- leak_K — у бота K утёкших вариантов КАЖДОГО семейства (реально сгенерированы из банка случайными зёрнами) с ключами:
  точное совпадение варианта → ключ; иначе — вариант, текст которого чаще всего был ключом в утёкших (эксплуатация
  постоянства ключа); иначе — собственные знания (θ на 0,75 логита ниже порога заявленного грейда);
- control — тот же «слабый» кандидат (θ на 0,75 ниже порога) без утечки и без хитростей.
Развёрнутые ответы ботов в прогоне без модели не засчитываются (x = None, «на проверке») — это в пользу бота
(у него меньше неверных ответов), т.е. оценка false_confirmed сверху. Время ответа бот подбирает «как у честного»
(модель времени банка) — худший для нас случай: детектор предзнания по скорости не помогает.

Запуск (из backend/):
    python -m app.modules.validation.cheat_bots --n 150 --out app/modules/validation/data/cheat_bots.json
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace
import zlib

import numpy as np

from app.modules.validation.product_sim import STAND_ENV, _finished, _git_commit, _rank, settings_snapshot, wilson

CLAIMS = ("junior", "middle", "senior")
SEED = 3301  # зерно ботов (не пересекается с TRAIN_SEEDS/TEST_SEEDS симуляции)
FINAL_SEED = 4501  # итоговый прогон на замороженном банке стенда (один, хэш банка — в коммите до прогона)
NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
WORD_RE = re.compile(r"[\wа-яё]{4,}", re.I)


def _h(*parts) -> str:
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:16]


class Bots:
    def __init__(self, seed: int = SEED):
        from assessment_bank import generate
        from app.modules.assessment.bank_engine import BankEngine
        from app.modules.catalog.ext import visible_directions
        from app.modules.catalog.seed_data import ALL_GRADE_CUTS

        self.generate = generate
        self.e = BankEngine()
        self.cuts = ALL_GRADE_CUTS
        self.directions = list(visible_directions())
        self.seed = seed
        self.rng = np.random.default_rng([seed, 1])
        self.leak: dict[str, list[tuple[str, str]]] = {}  # семейство → [(хэш условия, текст ключа)] на K_MAX вариантов
        self.k_max = 0

    # ---------------------------------------------------------------- утечка
    @staticmethod
    def _key_text(pub: dict, key: dict, fmt: str) -> str | None:
        v = key.get("value")
        if key.get("kind") == "option":
            for o in pub.get("options") or []:
                if o["id"] == v:
                    return (o.get("text") or "") + "\x1e" + (o.get("code") or "")
            return None
        if key.get("kind") == "line":
            lines = (pub.get("code") or "").split("\n")
            try:
                return lines[int(v) - 1].strip()
            except Exception:
                return None
        if key.get("kind") == "output":
            return str(v)
        if key.get("kind") == "steps" and isinstance(v, dict):
            out = []
            for s in ("1", "2"):
                tid = v.get(s)
                for o in pub.get("options") or []:
                    if o["id"] == tid and str(o.get("step", s)) == s:
                        out.append((o.get("text") or "") + "\x1e" + (o.get("code") or ""))
            return "\x1d".join(out)
        return None

    def leaked(self, fid: str, k: int) -> list[tuple[str, str]]:
        have = self.leak.setdefault(fid, [])
        r = np.random.default_rng([self.seed, 9, int(_h(fid), 16) % (2**31)])
        while len(have) < k:
            s = int(r.integers(0, 2**31 - 1))
            try:
                v = self.generate(fid, s)
                pub = v.public_view()
                key = v.answer_key.model_dump(include={"kind", "value", "accept"})
                have.append((_h(pub.get("stem"), pub.get("code")), self._key_text(pub, key, None) or ""))
            except Exception:
                have.append(("", ""))
        return have[:k]

    # ---------------------------------------------------------------- ответы
    def _option_ids(self, pub: dict, step: int, fmt: str) -> list[dict]:
        opts = pub.get("options") or []
        if fmt in ("open_book_3step", "incident_sim"):
            return [o for o in opts if int(o.get("step", 1)) == step]
        return opts

    def answer_for(self, strat: str, cur: dict, step: int, kind: str, theta: float | None, k: int) -> object:
        pub, key, fmt = cur["public"], cur["key"], cur["format"]
        opts = self._option_ids(pub, step, fmt)
        lines = (pub.get("code") or "").split("\n")
        # «знает» — для leak/control: верно с вероятностью p(θ) по параметрам задания банка (истина = банк)
        if strat in ("control",) or strat.startswith("leak_"):
            if strat.startswith("leak_"):
                got = self._leak_answer(cur, step, kind, opts, lines, k)
                if got is not None:
                    return got
            snap = cur["pool"]
            j = min(step - 1, len(snap["a"]) - 1)
            p = 1.0 / (1.0 + math.exp(-snap["a"][j] * (theta - snap["b"][j])))
            if self.rng.random() < p:
                return _correct(key, step, kind)
            return self._random(kind, opts, lines)
        if kind == "option":
            if strat == "random":
                return opts[int(self.rng.integers(len(opts)))]["id"]
            if strat.startswith("position_"):
                pos = "ABCDEFG".index(strat[-1])
                return opts[min(pos, len(opts) - 1)]["id"]
            if strat == "longest":
                return max(opts, key=lambda o: len((o.get("text") or "") + (o.get("code") or "")))["id"]
            if strat == "median_number":
                vals = []
                for o in opts:
                    m = NUM_RE.search(o.get("text") or "")
                    vals.append(float(m.group().replace(",", ".")) if m else None)
                if all(v is not None for v in vals) and len(set(vals)) > 2:
                    order = sorted(range(len(opts)), key=lambda i: vals[i])
                    return opts[order[len(order) // 2]]["id"]
                return max(opts, key=lambda o: len(o.get("text") or ""))["id"]
            if strat == "overlap":
                ctx = set(w.lower() for w in WORD_RE.findall((pub.get("stem") or "") + " " + (pub.get("code") or "")))
                return max(opts, key=lambda o: len(ctx & set(w.lower() for w in WORD_RE.findall(
                    (o.get("text") or "") + " " + (o.get("code") or "")))))["id"]
        if kind == "line":
            n = max(1, len(lines))
            if strat == "random":
                return int(self.rng.integers(1, n + 1))
            return max(1, n // 2)
        return "" if kind == "text" and fmt == "predict_output" else "Проверю логи, воспроизведу и исправлю."

    def _random(self, kind, opts, lines):
        if kind == "option" and opts:
            return opts[int(self.rng.integers(len(opts)))]["id"]
        if kind == "line":
            return int(self.rng.integers(1, max(2, len(lines) + 1)))
        return "не знаю"

    def _leak_answer(self, cur, step, kind, opts, lines, k):
        pub, fmt = cur["public"], cur["format"]
        lk = self.leaked(cur["family_id"], k)
        sh = _h(pub.get("stem"), pub.get("code"))
        exact = [kt for h, kt in lk if h == sh]
        freq = Counter(kt for _, kt in lk if kt)
        if fmt in ("open_book_3step", "incident_sim"):
            # ключ шагов 1–2 — пара текстов; берём часть для шага
            parts = Counter()
            for kt, c in freq.items():
                ps = kt.split("\x1d")
                if len(ps) >= step:
                    parts[ps[step - 1]] += c
            freq = parts
            exact = [e.split("\x1d")[step - 1] for e in exact if len(e.split("\x1d")) >= step]
        cand = exact[:1] or [t for t, _ in freq.most_common(3)]
        if kind == "option":
            texts = {(o.get("text") or "") + "\x1e" + (o.get("code") or ""): o["id"] for o in opts}
            for t in cand:
                if t in texts:
                    return texts[t]
            return None
        if kind == "line":
            for t in cand:
                for i, ln in enumerate(lines, 1):
                    lt = ln.strip()
                    if lt and lt == t:
                        return i
            return None
        if kind == "text" and fmt == "predict_output":
            return cand[0] if cand else None
        return None

    # ---------------------------------------------------------------- попытка
    def session(self, strat: str, direction: str, claim: str, k: int, *, refine_from=None, refine=None,
                seen=None, seen_seeds=None) -> tuple[dict, object]:
        e = self.e
        theta = self.cuts[claim] - 0.75
        st = e.start(direction=direction, claimed_grade=claim, stack_tags=[], seed=int(self.rng.integers(1, 2**31 - 1)),
                     refine_from=refine_from, refine=refine, seen=seen or {}, seen_seeds=seen_seeds or {})
        guard = 0
        while guard < 80:
            guard += 1
            it = e.next_item(st)
            if it is None:
                break
            cur = e._current(st)
            for step in range(1, cur["parts"] + 1):
                kind = e._answer_kind(cur, step)
                ans = self.answer_for(strat, cur, step, kind, theta, k)
                fb = e.answer(st, cur["token"], ans, step=step)
                if not fb.accepted:  # неверный формат ответа — бот отвечает «как получится»
                    fb = e.answer(st, cur["token"], self._random(kind, self._option_ids(cur["public"], step, cur["format"]),
                                                               (cur["public"].get("code") or "").split("\n")), step=step)
                    if not fb.accepted:
                        break
            if st.get("current") is not None:  # не удалось ответить — завершаем задание как пустое
                cur["done"] = True
                st["current"] = None
            snap = cur["pool"]  # время «как у честного» — детектор по скорости не срабатывает
            t = float(np.exp(self.rng.normal(float(snap["beta_time"]), 1.0 / float(snap["alpha_time"]))))
            t = max(5.0, min(t, float(cur["time_limit_s"])))
            cur["time_s"], cur["log_t"], cur["overtime"] = t, math.log(t), False
        return st, e.finish(st)

    def use_stream(self, strat: str) -> None:
        """Свой поток случайных чисел у каждой стратегии (зерно бота + имя стратегии): результат стратегии не зависит
        от порядка и от того, считаются ли стратегии в одном процессе или параллельно (шарды пода)."""
        self.rng = np.random.default_rng([self.seed, 1, zlib.crc32(strat.encode())])

    def attempt(self, strat: str, k: int = 0) -> dict:
        from app.modules.assessment import two_stage as ts_mod

        d = self.directions[int(self.rng.integers(len(self.directions)))]
        claim = CLAIMS[int(self.rng.integers(len(CLAIMS)))]
        st, res = self.session(strat, d, claim, k)
        er = {"confirmed": res.confirmed, "provisional": res.provisional, "theta": res.theta, "se": res.se}
        ts = SimpleNamespace(status=_finished(), claimed_grade_id=claim, direction_id=d,
                             result={"engine": self.e.name, "engine_result": er, "state": st, "mode": "full"})
        g = ts_mod.session_grade(ts)
        v = (res.details or {}).get("verdict") or {}
        status_now, llr_now = v.get("status"), float(v.get("llr") or 0.0)
        out = {"strategy": strat, "k": k, "direction": d, "claim": claim, "verdict_main": v.get("status"),
               "oral": bool(v.get("oral_defense_required")),
               "integrity": ((res.details or {}).get("integrity") or {}).get("level"),
               "preknowledge": bool(((res.details or {}).get("preknowledge") or {}).get("flagged")),
               "grade_main": g, "refined": False,
               "items": sum(1 for i in st["items"] if i.get("done") and not i.get("canary"))}
        tp = ts_mod.params()
        b = ts_mod.session_boundary(ts, tp) if tp["enabled"] else None
        if b is not None:
            p2 = ts_mod.ext_params(tp, b.cut_grade)
            fams = {i["family_id"]: 0 for i in st["items"]}
            seeds = {i["family_id"]: [int(i["seed"])] for i in st["items"]}
            st2, res2 = self.session(strat, d, claim, k, refine_from=dict(st, final_theta=res.theta, final_se=res.se),
                                     refine={**b.as_dict(), "level": p2["level"], "items": int(p2["items"]),
                                             "minutes": int(p2["minutes"]), "confirm": p2["confirm"],
                                             "confirm_up": p2["confirm_up"], "floor": p2["floor"],
                                             "source_session_id": "bot"}, seen=fams, seen_seeds=seeds)
            g = ((res2.details or {}).get("two_stage") or {}).get("final_grade") or "none"
            v2 = (res2.details or {}).get("verdict") or {}
            status_now, llr_now = v2.get("status"), float(v2.get("llr") or 0.0)
            out.update(refined=True, items=out["items"] + sum(1 for i in st2["items"] if i.get("done") and not i.get("canary")))
        out["grade_final"] = g
        out["provisional"] = bool(res.provisional) and not out["refined"]
        from app.modules.assessment import sprt as sp

        if sp.sprt_on():
            # поправка №2: итог — тот же путь, что у кандидата: SPRT после основной части → второй этап → устная
            # защита (консервативная модель product_sim: бот отвечает на ней своими знаниями, θ = порог − 0,75)
            if status_now == "needs_followup":
                from app.modules.validation.product_sim import ORAL_A, ORAL_K

                cut = float(self.cuts[claim])
                theta = cut - 0.75
                xo = (self.rng.random(ORAL_K) < 1.0 / (1.0 + np.exp(-ORAL_A * (theta - cut)))).astype(float)
                vp = sp.verdict_params()
                status_now = sp.sprt_status(llr_now + sp.llr3(xo, [ORAL_A] * ORAL_K, [cut] * ORAL_K, [0.0] * ORAL_K,
                                                              cut, vp["delta"]), vp["alpha"], vp["beta"])
                out["oral_model"] = True
            out["verdict_final"] = status_now
            out["false_confirmed"] = status_now == "confirmed"
            return out
        # строгое подтверждение: категория по основной части или итог второго этапа не ниже заявки;
        # «Junior (предварительно)» — не подтверждение (считается отдельно: provisional)
        out["false_confirmed"] = (_rank(g) >= _rank(claim)) if out["refined"] else bool(res.confirmed)
        return out


def _key_dict(v) -> dict:
    k = v.answer_key
    if isinstance(k, dict):
        return k
    return {"kind": getattr(k, "kind", None), "value": getattr(k, "value", None), "accept": list(getattr(k, "accept", []) or [])}


def _correct(key: dict, step: int, kind: str):
    v = key.get("value")
    if key.get("kind") == "steps" and isinstance(v, dict):
        return v.get(str(step))
    if kind == "line":
        return int(v)
    return v


def merge(files: list[str], out: str) -> int:
    """Сведение шардов по стратегиям (у каждой стратегии свой поток случайных чисел — результат от разбиения не
    зависит): таблицы объединяются, meta — первого шарда + список шардов."""
    parts = [json.loads(Path(f).read_text(encoding="utf-8")) for f in files]
    table: dict = {}
    for d in parts:
        table.update(d.get("table") or {})
    meta = dict(parts[0]["meta"])
    meta["shards"] = [{"file": Path(f).name, "strategies": sorted((d.get("table") or {}).keys()),
                       "elapsed_s": (d.get("meta") or {}).get("elapsed_s"), "git_commit": (d.get("meta") or {}).get("git_commit"),
                       "engine_errors": (d.get("meta") or {}).get("engine_errors")} for f, d in zip(files, parts)]
    meta["engine_errors"] = {"n": sum(((d.get("meta") or {}).get("engine_errors") or {}).get("n", 0) for d in parts)}
    meta["command_merge"] = "cd backend && python -m app.modules.validation.cheat_bots merge --out " + out + " " + \
        " ".join(Path(f).name for f in files)
    order = ["control"] + sorted(k for k in table if k != "control" and not k.startswith("leak_")) + \
        sorted((k for k in table if k.startswith("leak_")), key=lambda k: int(k.split("_")[1]))
    Path(out).write_text(json.dumps({"meta": meta, "table": {k: table[k] for k in order}}, ensure_ascii=False,
                                    indent=1, default=str) + "\n", encoding="utf-8")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "merge":
        mp = argparse.ArgumentParser()
        mp.add_argument("--out", required=True)
        mp.add_argument("files", nargs="+")
        m = mp.parse_args(argv[1:])
        return merge(m.files, m.out)
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150, help="попыток на стратегию")
    ap.add_argument("--k", type=str, default="10,100", help="K утёкших вариантов на семейство")
    ap.add_argument("--strategies", type=str, default="control,random,position_A,position_B,position_C,position_D,longest,median_number,overlap")
    ap.add_argument("--out", type=str, required=True)
    ap.add_argument("--final", action="store_true", help="итоговый прогон: FINAL_SEED и проверка хэша банка")
    ap.add_argument("--expect-bank-hash", type=str, default="")
    a = ap.parse_args(argv)
    seed = SEED
    if a.final:
        from app.modules.validation.product_sim import FINAL_SEEDS, check_final_bank

        check_final_bank(FINAL_SEEDS, a.expect_bank_hash)
        seed = FINAL_SEED
    bots = Bots(seed)
    plan = [(s, 0) for s in a.strategies.split(",") if s] + [(f"leak_{k}", int(k)) for k in a.k.split(",") if k]
    rows, t0 = [], time.time()
    errors: list[str] = []
    for strat, k in plan:
        bots.use_stream(strat)
        for i in range(a.n):
            try:
                rows.append(bots.attempt(strat, k))
            except Exception as ex:
                errors.append(f"{strat}: {type(ex).__name__}: {ex}"[:200])
        print(f"{strat}: {time.time() - t0:.0f} с", file=sys.stderr, flush=True)
    by = defaultdict(list)
    for r in rows:
        by[r["strategy"]].append(r)
    table = {}
    for s, rs in by.items():
        n = len(rs)
        fc = sum(r["false_confirmed"] for r in rs)
        table[s] = {"n": n, "false_confirmed": {"k": fc, "value": round(fc / n, 4), "ci95": wilson(fc, n)},
                    "needs_followup_main": round(sum(r["verdict_main"] == "needs_followup" for r in rs) / n, 4),
                    "provisional_junior": {"k": sum(r.get("provisional", False) for r in rs),
                                           "value": round(sum(r.get("provisional", False) for r in rs) / n, 4)},
                    "oral_defense": round(sum(r["oral"] for r in rs) / n, 4),
                    "preknowledge_flag": round(sum(r["preknowledge"] for r in rs) / n, 4),
                    "integrity_low": round(sum(r["integrity"] == "low" for r in rs) / n, 4),
                    "by_claim": {c: {"n": sum(1 for r in rs if r["claim"] == c),
                                     "false_confirmed": sum(1 for r in rs if r["claim"] == c and r["false_confirmed"])}
                                 for c in CLAIMS}}
    meta = {"what": "боты-стратегии через движок продукта (реальные варианты и проверка ответа), не люди",
            "n_per_strategy": a.n, "k_values": a.k, "seed": seed, "final": a.final, "claims": CLAIMS,
            "bot_theta": "порог заявленного грейда − 0,75 логита (для control и leak_K)",
            "text_answers": "без модели не засчитываются (в пользу бота — оценка сверху)",
            "settings": settings_snapshot(), "bank_families": bots.e.n_families, "git_commit": _git_commit(),
            "date": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "command": "cd backend && python -m app.modules.validation.cheat_bots " + " ".join(argv),
            "engine_errors": {"n": len(errors), "examples": Counter(errors).most_common(5)},
            "elapsed_s": round(time.time() - t0, 1)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"meta": meta, "table": table}, ensure_ascii=False, indent=1, default=str) + "\n",
                           encoding="utf-8")
    print(json.dumps(table, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    for kk, vv in STAND_ENV.items():
        os.environ.setdefault(kk, vv)
    raise SystemExit(main())
