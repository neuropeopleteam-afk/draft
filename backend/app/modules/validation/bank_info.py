"""Информация банка у порогов грейдов: где тесту не хватает заданий (А4 → А3, 21.10.2026).

Что считаем — по тем же правилам, что у кандидата (``bank_engine._pool``, ``AppCATSession``):
- пул сессии = общий блок + блок направления, один из ``ASSESSMENT_SUBPOOLS`` субпулов (вторая попытка — другой
  субпул, поэтому нужен полный набор в КАЖДОМ субпуле); канарейки не считаются;
- семейства с условием по стеку (Go, Java, Django…) выдаются только тем, у кого этот тег есть в стеке, — считаются
  отдельно и в «доступно всем» не входят;
- информация задания у порога θ = cut — сумма информаций частей по модели движка: наклон a_eff (с разбросом
  вариантов), трудность b, угадывание c = 1/4 в частях с выбором варианта (``AppCATSession._guess_c``), c = 0 в
  коде, выводе, строке и тексте; I = (dP/dθ)² / (P(1 − P));
- лучший набор из N заданий у порога — жадно по информации при ограничениях продукта: доля общего блока ≈ 40 %,
  не меньше трети — код и открытые ответы (``CODE_OPEN_FORMATS``), не больше двух длинных заданий.

«Полезное у порога» задание — информация в пороге не меньше ``USEFUL_SHARE`` от максимума своего формата
(для вопроса с выбором при a_eff ≈ 2 это b ∈ [порог − 0,9; порог + 0,45], для кода при a ≈ 1,1 — порог ± 1,25).

Потребность (на субпул): тест у спорного порога до ``N_TARGET`` заданий с квотой ≥ 1/3 практических и долей общего
блока 40 % → в блоке направления ``NEED_DIR`` полезных заданий по типам, в общем блоке ``NEED_COMMON``.
Нехватка = max(0, нужно − есть). Это рабочий список для банка (не цифра для сайта).

Запуск (из backend/):
    python -m app.modules.validation.bank_info --out app/modules/validation/data/bank_info_cuts.json \
        --md ../docs/validation/BANK_INFO_CUTS.md
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import datetime as dt
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

USEFUL_SHARE = 0.6
BUDGET_S = 3600.0  # основная часть до 60 минут
SHORT_S = 80.0  # ожидаемое время «короткого» практического задания (лимит ≈ 140 с при медиане 0,45 · лимит)
N_TARGET = 24
COMMON_SHARE = 0.4
CODE_SHARE = 1.0 / 3.0
LONG = {"open_answer", "open_book_3step", "incident_sim"}
OPTION_PARTS = {"mcq_concept": None, "choose_fix": None, "open_book_3step": (0, 1), "incident_sim": (0, 1)}


def _need() -> tuple[dict, dict]:
    n_code = math.ceil(N_TARGET * CODE_SHARE)
    n_mcq = N_TARGET - n_code
    n_common = round(N_TARGET * COMMON_SHARE)
    share_dir = 1.0 - n_common / N_TARGET
    need_dir = {"mcq": math.ceil(n_mcq * share_dir), "code": math.ceil(n_code * share_dir)}
    need_common = {"mcq": n_mcq - need_dir["mcq"], "code": max(0, n_code - need_dir["code"])}
    return need_dir, need_common


def guess_c(it) -> np.ndarray:
    n = len(np.atleast_1d(it.b))
    c = np.zeros(n)
    parts = OPTION_PARTS.get(it.format, ())
    if parts is None:
        c[:] = 0.25
    else:
        for j in parts:
            if j < n:
                c[j] = 0.25
    return c


def info(it, theta: float) -> float:
    a = np.asarray(it.a_eff, dtype=float)
    b = np.asarray(it.b, dtype=float)
    c = guess_c(it)
    s = 1.0 / (1.0 + np.exp(-np.clip(a * (theta - b), -30, 30)))
    p = c + (1.0 - c) * s
    d = (1.0 - c) * a * s * (1.0 - s)
    return float(np.sum(d * d / np.clip(p * (1.0 - p), 1e-12, None)))


def kind(it) -> str:
    from app.modules.assessment.sprt import CODE_OPEN_FORMATS

    return "code" if it.format in CODE_OPEN_FORMATS else "mcq"


GRID = np.linspace(-3.5, 4.5, 161)


def peak(it) -> float:
    """Максимум информации задания по шкале (на сетке 0,05 логита)."""
    return max(info(it, float(t)) for t in GRID)


def useful(it, cut: float, pk: dict) -> bool:
    """Задание нацелено на этот порог: информация в пороге ≥ USEFUL_SHARE от собственного максимума задания."""
    return info(it, cut) >= USEFUL_SHARE * pk[it.family_id]


def type_max(items, pk: dict) -> dict[str, float]:
    """Типичный максимум информации задания своего типа (медиана по банку) — для «идеального» набора."""
    out: dict[str, list] = defaultdict(list)
    for it in items:
        out[kind(it)].append(pk[it.family_id])
    return {k: float(np.median(v)) for k, v in out.items()}


def best_set(items, cut: float, n: int) -> tuple[float, dict]:
    """Жадный набор из n заданий у порога при ограничениях продукта; (сумма информации, состав)."""
    scored = sorted(items, key=lambda i: -info(i, cut))
    n_common = round(n * COMMON_SHARE)
    n_code = math.ceil(n * CODE_SHARE)
    take: list = []
    cnt = {"common": 0, "dir": 0, "code": 0, "mcq": 0, "long": 0}
    # сначала квота практических, затем остальное — как фильтр квоты движка (filter_code_open_pool)
    for want_code in (True, False):
        for it in scored:
            if len(take) >= n or it in take:
                continue
            k = kind(it)
            if want_code and k != "code":
                continue
            if want_code and cnt["code"] >= n_code:
                break
            blk = "common" if it.block == "common" else "dir"
            cap = n_common if blk == "common" else n - n_common
            if cnt[blk] >= cap:
                continue
            if it.format in LONG and cnt["long"] >= 2:
                continue
            take.append(it)
            cnt[blk] += 1
            cnt[k] += 1
            cnt["long"] += it.format in LONG
    tot = sum(info(i, cut) for i in take)
    return tot, {**cnt, "n": len(take)}


def exp_time_s(it) -> float:
    """Ожидаемое время ответа (модель времени банка: lognormal, медиана 0,45 · лимит, σ = 1/α)."""
    return float(np.exp(it.beta_time + 0.5 / (it.alpha_time ** 2)))


def best_time(items, cut: float, budget_s: float, extra: list | None = None) -> tuple[float, dict]:
    """Лучший набор у порога в бюджете времени: жадно по информации на секунду ожидаемого времени, при ≥ 1/3
    практических по числу, общем блоке ≤ 40 % и ≤ 2 длинных заданиях. extra — гипотетические задания (info, t, kind)."""
    cand = [(info(i, cut), exp_time_s(i), kind(i), i.block == "common", i.format in LONG) for i in items]
    cand += list(extra or [])
    cand.sort(key=lambda r: -r[0] / max(r[1], 1.0))
    used_t, tot = 0.0, 0.0
    cnt = {"n": 0, "code": 0, "common": 0, "long": 0}
    pending_mcq = []
    for r in cand:
        inf, t, k, com, lg = r
        if used_t + t > budget_s or (lg and cnt["long"] >= 2):
            continue
        if com and cnt["common"] + 1 > COMMON_SHARE * (cnt["n"] + 1) + 1:
            continue
        if k == "mcq" and cnt["n"] > 0 and cnt["code"] < CODE_SHARE * (cnt["n"] + 1) - 1:
            pending_mcq.append(r)  # квота: сперва практическое
            continue
        used_t += t
        tot += inf
        cnt["n"] += 1
        cnt["code"] += k == "code"
        cnt["common"] += com
        cnt["long"] += lg
    return tot, {**cnt, "minutes": round(used_t / 60.0, 1)}


def code_needed(items, cut: float, budget_s: float, se_target: float, proto: tuple) -> int | None:
    """Сколько практических заданий-образцов (информация и время — как у медианного практического задания банка,
    трудность ровно у порога) добавить, чтобы SE в бюджете времени стало ≤ se_target; None — недостижимо (> 60)."""
    for k in range(0, 61):
        tot, _ = best_time(items, cut, budget_s, extra=[proto] * k)
        if tot > 0 and 1.0 / math.sqrt(tot) <= se_target:
            return k
    return None


def ideal(n: int, tmax: dict[str, float]) -> float:
    n_code = math.ceil(n * CODE_SHARE)
    return (n - n_code) * tmax.get("mcq", 0.0) + n_code * tmax.get("code", 0.0)


def build() -> dict:
    from app.core.config import get_settings
    from app.modules.assessment.bank_engine import _pool, _stack_gates, bank_manifest
    from app.modules.catalog import levels
    from app.modules.catalog.ext import visible_directions
    from app.modules.catalog.seed_data import ALL_GRADE_CUTS

    n_sub = max(1, get_settings().assessment_subpools)
    from app.modules.assessment.intern_pool import intern_family_ids
    from app.modules.catalog.seed_data import EXT_GRADE_ORDER

    pool = [p for p in _pool(n_sub) if not p.canary]
    gates = _stack_gates()
    pk = {p.family_id: peak(p) for p in pool}
    tmax = type_max(pool, pk)
    code_items = [p for p in pool if kind(p) == "code" and p.format not in LONG]
    proto = (float(np.median([pk[p.family_id] for p in code_items])), float(np.median([exp_time_s(p) for p in code_items])),
             "code", False, False)
    no_rotation = {"intern"} | (set(EXT_GRADE_ORDER) if get_settings().grades_ext_no_subpool else set())
    need_dir, need_common = _need()
    rows = []
    common_rows = []
    for g, cut in ALL_GRADE_CUTS.items():
        for sp in range(n_sub):
            com = [i for i in pool if i.block == "common" and i.subpool == sp and i.family_id not in gates]
            have = {k: sum(1 for i in com if kind(i) == k and useful(i, cut, pk)) for k in ("mcq", "code")}
            common_rows.append({"grade": g, "cut": cut, "subpool": sp, "useful": have,
                                "need": need_common, "short": {k: max(0, need_common[k] - have[k]) for k in have}})
    for d in visible_directions():
        grades = levels.available_grades(d)
        for g in grades:
            cut = float(ALL_GRADE_CUTS[g])
            # Стажёр и Lead/Principal — без ротации субпулов (как в bank_engine.start): весь пул направления;
            # у Стажёра — только семейства теста Стажёра (intern_pool)
            subs = [None] if g in no_rotation else list(range(n_sub))
            keep = intern_family_ids(pool, d) if g == "intern" else None
            for sp in subs:
                sess = [i for i in pool if i.block in ("common", d) and (sp is None or i.subpool == sp)
                        and (keep is None or i.family_id in keep)]
                open_all = [i for i in sess if i.family_id not in gates]
                own = [i for i in open_all if i.block == d]
                gated_own = [i for i in sess if i.block == d and i.family_id in gates]
                mult = 1 if sp is not None else n_sub  # без ротации пул общий: нужно столько, сколько на все субпулы
                need = {k: v * mult for k, v in need_dir.items()}
                have = {k: sum(1 for i in own if kind(i) == k and useful(i, cut, pk)) for k in ("mcq", "code")}
                have_gated = {k: sum(1 for i in gated_own if kind(i) == k and useful(i, cut, pk)) for k in ("mcq", "code")}
                t60, c60 = best_time(open_all, cut, BUDGET_S)
                need32 = code_needed(open_all, cut, BUDGET_S, 0.32, proto)
                need35 = code_needed(open_all, cut, BUDGET_S, 0.35, proto)
                i16, c16 = best_set(open_all, cut, 16)
                i24, c24 = best_set(open_all, cut, N_TARGET)
                rows.append({
                    "direction": d, "grade": g, "cut": cut, "subpool": sp,
                    "rotation": sp is not None,
                    "useful_dir": have, "useful_dir_stack_gated": have_gated, "need_dir": need,
                    "short_dir": {k: max(0, need[k] - have[k]) for k in have},
                    "info16": round(i16, 2), "se16": round(1 / math.sqrt(i16), 3) if i16 > 0 else None,
                    "info24": round(i24, 2), "se24": round(1 / math.sqrt(i24), 3) if i24 > 0 else None,
                    "ideal24": round(ideal(N_TARGET, tmax), 2),
                    "se24_ideal": round(1 / math.sqrt(ideal(N_TARGET, tmax)), 3),
                    "set24": c24, "set16": c16,
                    "info60": round(t60, 2), "se60": round(1 / math.sqrt(t60), 3) if t60 > 0 else None, "set60": c60,
                    "code_needed_se035": need35, "code_needed_se032": need32,
                })
    # без ротации субпулов в основной части (весь пул направления; повторная попытка — новые семейства через seen):
    # погрешность в бюджете 60 минут и сколько практических заданий у порога добавить до SE ≤ 0,35 — обычных
    # (медианное время практического задания банка) и коротких (ожидаемое время SHORT_S)
    merged = []
    short = (proto[0], SHORT_S, "code", False, False)
    for d in visible_directions():
        for g in levels.available_grades(d):
            cut = float(ALL_GRADE_CUTS[g])
            keep = intern_family_ids(pool, d) if g == "intern" else None
            sess = [i for i in pool if i.block in ("common", d) and i.family_id not in gates
                    and (keep is None or i.family_id in keep)]
            t60, c60 = best_time(sess, cut, BUDGET_S)
            merged.append({"direction": d, "grade": g, "cut": cut, "se60": round(1 / math.sqrt(t60), 3) if t60 > 0 else None,
                           "set60": c60, "need035_regular": code_needed(sess, cut, BUDGET_S, 0.35, proto),
                           "need035_short": code_needed(sess, cut, BUDGET_S, 0.35, short)})
    man = bank_manifest()
    return {
        "what": "информация банка у порогов грейдов по правилам выдачи продукта (рабочий список для банка, не цифра сайта)",
        "bank": {k: man.get(k) for k in ("commit", "content_hash", "n_families", "synced_at")},
        "subpools": n_sub, "useful_share": USEFUL_SHARE, "n_target": N_TARGET, "common_share": COMMON_SHARE,
        "code_share": round(CODE_SHARE, 4), "type_max_info": {k: round(v, 3) for k, v in tmax.items()},
        "need_dir_per_subpool": need_dir, "need_common_per_subpool": need_common,
        "code_proto": {"info": round(proto[0], 3), "time_s": round(proto[1], 1)},
        "rows": rows, "common": common_rows, "merged_pool": merged, "short_item_time_s": SHORT_S,
        "date": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "command": "cd backend && python -m app.modules.validation.bank_info " + " ".join(sys.argv[1:]),
    }


def markdown(r: dict) -> str:
    L = ["# Информация банка у порогов грейдов — что добавить в банк (А4 → А3)", "",
         f"Банк {r['bank'].get('commit')} ({r['bank'].get('n_families')} семейств, снимок {r['bank'].get('content_hash')}), "
         f"субпулов {r['subpools']}. Генерируется `{r['command']}`; это рабочий список, не цифра для сайта.", "",
         f"Правило: тест у спорного порога — до {r['n_target']} заданий, ≥ 1/3 практических (код, вывод, строка с "
         f"ошибкой, развёрнутый ответ), общий блок ≈ {round(100 * r['common_share'])} %. Значит, в КАЖДОМ субпуле "
         f"нужно полезных у порога заданий направления: вопросов с выбором — {r['need_dir_per_subpool']['mcq']}, "
         f"практических — {r['need_dir_per_subpool']['code']}; общего блока на порог: "
         f"{r['need_common_per_subpool']['mcq']} и {r['need_common_per_subpool']['code']}. «Полезное» — информация в "
         f"пороге ≥ {round(100 * r['useful_share'])} % от собственного максимума задания (порог попадает в «окно» задания; "
         f"типичный максимум: вопрос с выбором {r['type_max_info'].get('mcq')}, практическое "
         f"{r['type_max_info'].get('code')}). Стажёр и Lead/Principal идут без ротации субпулов — для них «нужно» "
         f"сразу на весь пул.", "",
         "SE24 — погрешность оценки уровня у порога после лучших 24 заданий субпула (меньше — лучше); "
         f"идеал при тех же форматах — {r['rows'][0]['se24_ideal'] if r['rows'] else '—'}.", ""]
    by = defaultdict(list)
    for x in r["rows"]:
        by[(x["direction"], x["grade"])].append(x)
    L += ["## Нехватка по направлениям (сумма по субпулам: вопросы с выбором / практические)", "",
          "| Направление | Порог | Есть (по субпулам) | Нехватка | SE24 по субпулам | С условием по стеку |",
          "|---|---|---|---|---|---|"]
    tot = defaultdict(int)
    for (d, g), xs in by.items():
        have = " · ".join(f"{x['useful_dir']['mcq']}/{x['useful_dir']['code']}" for x in xs)
        sm = sum(x["short_dir"]["mcq"] for x in xs)
        sc = sum(x["short_dir"]["code"] for x in xs)
        tot["mcq"] += sm
        tot["code"] += sc
        se = " · ".join(f"{x['se24']}" for x in xs)
        gated = " · ".join(f"{x['useful_dir_stack_gated']['mcq']}/{x['useful_dir_stack_gated']['code']}" for x in xs)
        flag = "" if (sm or sc) else " (хватает)"
        rot = "" if xs[0]["rotation"] else " — без ротации, весь пул"
        L.append(f"| {d} | {g} ({xs[0]['cut']:+.2f}){rot} | {have} | {sm} / {sc}{flag} | {se} | {gated} |")
    L += ["", f"Итого не хватает в блоках направлений: вопросов с выбором — {tot['mcq']}, практических — {tot['code']}.", "",
          "## Общий блок по порогам (на субпул: есть / нужно / нехватка — вопросы с выбором и практические)", "",
          "| Порог | Субпул | Есть | Нужно | Нехватка |", "|---|---|---|---|---|"]
    for x in r["common"]:
        L.append(f"| {x['grade']} ({x['cut']:+.2f}) | {x['subpool']} | {x['useful']['mcq']}/{x['useful']['code']} | "
                 f"{x['need']['mcq']}/{x['need']['code']} | {x['short']['mcq']}/{x['short']['code']} |")
    if r.get("merged_pool"):
        L += ["", "## Без ротации субпулов: погрешность за 60 минут и сколько практических заданий добавить (до SE ≤ 0,35)", "",
              f"Практическое задание-образец: информация {r['code_proto']['info']} (медиана банка), время — обычное "
              f"{r['code_proto']['time_s']} с или короткое {r['short_item_time_s']} с; трудность — у порога.", "",
              "| Порог | " + " | ".join(dict.fromkeys(x["direction"] for x in r["merged_pool"])) + " | Всего |",
              "|---|" + "---|" * (len(dict.fromkeys(x["direction"] for x in r["merged_pool"])) + 1)]
        by_g = defaultdict(list)
        for x in r["merged_pool"]:
            by_g[(x["grade"], x["cut"])].append(x)
        for (g, cut), xs in by_g.items():
            cells = [f"SE {x['se60']} → +{x['need035_regular']} / +{x['need035_short']}" for x in xs]
            L.append(f"| {g} ({cut:+.2f}) | " + " | ".join(cells) + f" | +{sum(x['need035_regular'] or 0 for x in xs)} / "
                     f"+{sum(x['need035_short'] or 0 for x in xs)} |")
        L += ["", "Ячейка: погрешность сейчас → сколько добавить обычных / коротких практических заданий у этого порога."]
    L += ["", "Как читать: «полезное у порога» вопрос с выбором — трудность b примерно от порога − 0,9 до порога + 0,45; "
          "практическое — от порога − 1,25 до порога + 1,25. Новые задания нужны именно с такой трудностью; задания с "
          "условием по стеку видят только кандидаты с этим тегом — в «есть» они не входят.", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--md", default="")
    a = ap.parse_args(argv)
    r = build()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(r, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if a.md:
        Path(a.md).write_text(markdown(r), encoding="utf-8")
    print(markdown(r))
    return 0


if __name__ == "__main__":
    for k, v in {"GRADES_EXT_ENABLED": "true", "CATALOG_EXT_ENABLED": "1", "LLM_DISABLED": "true"}.items():
        os.environ.setdefault(k, v)
    raise SystemExit(main())
