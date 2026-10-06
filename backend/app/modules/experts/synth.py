"""Синтетическая разметка — проверка, что расчёт работает (не результат и не замена экспертам).

Три «эксперта» S1–S3 с назначениями слотов E1–E3 и заложенной истиной:
* A — истинная релевантность = разметка по правилам, оценка эксперта = истина + шум N(0; 0,55), округление в 0–3;
* B — истинный уровень по замыслу автора ответа (high 3, medium 2, low 1), шум N(0; 0,5); критерии — от уровня;
  контрольные ответы помечаются флагом с вероятностью 0,8;
* C — заложенные пороги θ (0,2 и 1,15 — нарочно не равны текущим 0 и 1): доля = 100·E_i(θ + смещение эксперта) + шум;
* модель-оценщик — две синтетические модели: «точная» (шум 0,1) и «внушаемая» (шум 0,3, поддаётся инструкции в ответе).
Проверка: расчёт должен восстановить заложенные пороги и упорядочить модели по согласию.
"""
from __future__ import annotations

import numpy as np

from app.modules.experts import analysis as A
from app.modules.experts import stats as S
from app.modules.experts.pack import SLOTS, assignment_from_rows

PLANTED_CUTS = {"junior_middle": 0.2, "middle_senior": 1.15}
TIER = {"high": 3, "medium": 2, "low": 1}


def _snap(x: float) -> float:
    return min((0.0, 0.5, 1.0), key=lambda c: abs(c - x))


def make(items: dict, seed: int = 7) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows = [(it["kind"], k, it["grp"], it["hidden"]) for k, it in items.items()]
    labels = []
    for si, slot in enumerate(SLOTS):
        coder = f"S{si + 1}"
        asg = assignment_from_rows(rows, slot, 3)
        bias = {b: float(rng.normal(0, 0.15)) for b in PLANTED_CUTS}
        for k in asg["A"]:
            t = items[k]["hidden"]["rule_label"]
            labels.append({"coder": coder, "key": k,
                           "value": {"relevance": int(np.clip(round(t + rng.normal(0, 0.55)), 0, 3))}})
        for k in asg["B"]:
            h = items[k]["hidden"]
            t = 1 if h.get("control") == "injection" else TIER.get(h.get("intended"), 2)
            hol = int(np.clip(round(t + rng.normal(0, 0.5)), 0, 3))
            crit = {c["id"]: _snap(t / 3 + rng.normal(0, 0.2)) for c in items[k]["payload"]["rubric"]["criteria"]}
            flag = h["control"] if h.get("control") and rng.random() < 0.8 else "none"
            labels.append({"coder": coder, "key": k, "value": {"criteria": crit, "holistic": hol, "flag": flag}})
        for k in asg["C"]:
            h, floor = items[k]["hidden"], int(items[k]["payload"].get("floor") or 0)
            v = {}
            for b, cut in PLANTED_CUTS.items():
                p = 100 * S.expected_share(cut + bias[b], h["a"], h["b"]) + rng.normal(0, 8)
                v[b] = int(np.clip(5 * round(p / 5), max(5, floor), 95))
            v["middle_senior"] = max(v["middle_senior"], v["junior_middle"])
            v["confidence"] = int(rng.integers(1, 4))
            labels.append({"coder": coder, "key": k, "value": v})
    return labels


def synth_llm(items: dict, seed: int = 11) -> dict:
    """Синтетические оценки двух «моделей» по трём прогонам — в формате hidden['llm']."""
    rng = np.random.default_rng(seed)
    out: dict = {}
    for k, it in items.items():
        if it["kind"] != "B":
            continue
        h = it["hidden"]
        t = TIER.get(h.get("intended"), 2) / 3
        if h.get("control") == "injection":
            t = 1 / 3
        runs = {}
        for m, sd, fooled in (("synthetic-precise", 0.08, False), ("synthetic-suggestible", 0.25, True)):
            base = 1.0 if (fooled and h.get("control") == "injection") else t
            runs[m] = [{"status": "scored", "score": float(np.clip(base + rng.normal(0, sd), 0, 1)),
                        "latency_ms": int(rng.integers(900, 2500))} for _ in range(3)]
        out[k] = runs
    return out


def check(items: dict) -> dict:
    """Синтетическая разметка → тот же расчёт → сверка с заложенной истиной."""
    labels = make(items)
    llm = synth_llm(items)
    items2 = {k: ({**it, "hidden": {**it["hidden"], "llm": llm.get(k, {})}} if it["kind"] == "B" else it)
              for k, it in items.items()}
    res = A.analyze(items2, labels)
    rec = {b["boundary"]: b["angoff"] for b in (res["angoff"] or {}).get("boundaries", [])}
    models = {m["model"]: m for m in (res["llm"] or {}).get("models", [])}
    checks = [
        {"what": "Порог Junior → Middle восстановлен", "planted": PLANTED_CUTS["junior_middle"],
         "got": rec.get("junior_middle"),
         "ok": rec.get("junior_middle") is not None and abs(rec["junior_middle"] - PLANTED_CUTS["junior_middle"]) < 0.3},
        {"what": "Порог Middle → Senior восстановлен", "planted": PLANTED_CUTS["middle_senior"],
         "got": rec.get("middle_senior"),
         "ok": rec.get("middle_senior") is not None and abs(rec["middle_senior"] - PLANTED_CUTS["middle_senior"]) < 0.3},
        {"what": "Точная модель допустима, внушаемая — нет", "planted": "precise", "got": (res["llm"] or {}).get("choice"),
         "ok": bool(models.get("synthetic-precise", {}).get("admissible")) and
               models.get("synthetic-suggestible", {}).get("admissible") is False},
        {"what": "Согласие экспертов существенное (шум 0,55 балла)", "planted": "≥ 0,61",
         "got": res["agreement"]["A"]["kappa_mean"], "ok": (res["agreement"]["A"]["kappa_mean"] or 0) >= 0.61},
    ]
    res["checks"] = checks
    res["ok"] = all(c["ok"] for c in checks)
    res["synthetic"] = True
    return res
