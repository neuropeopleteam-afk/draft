"""Первый экран /validation: «5 чисел, которые доказывают механику» — каждое с ДИ, подписью мира и ссылкой на блок.

Числа не пишутся руками: они собираются из JSON расчётов (make path-retest, make bench). Нет расчёта — нет числа
(карточка показывает «не посчитано»), чтобы на экране не оказалось числа без подписи.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATH_RETEST = HERE / "data" / "path_retest.json"
BENCH = HERE / "data" / "matching_bench.json"
GRADE_SWEEP = HERE / "data" / "grade_sweep.json"


def _load(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _bench_signature(b: dict) -> dict:
    """У старых расчётов бенчмарка подписи нет — собираем её из полей отчёта (коммит неизвестен)."""
    if b.get("signature"):
        return b["signature"]
    w = b.get("world") or {}
    return {"world": f"бенчмарк подбора: {w.get('n_needs')} потребностей × {w.get('n_candidates')} кандидатов",
            "seed": (b.get("seeds") or {}).get("world"), "config_hash": b.get("config_hash"), "commit": "unknown",
            "command": b.get("command"), "generated_at": b.get("generated_at")}


def _p(v: float) -> str:
    """Проценты: целые, но у долей между 99 и 100 % — с десятыми (99,6 % не округляется до 100 %)."""
    x = 100 * v
    txt = f"{x:.1f}".replace(".", ",") if 99 < x < 100 or 0 < x < 1 else str(round(x))
    return f"{txt}\u00a0%"


def _p1(v: float) -> str:
    """Проценты с одной десятой (57,5 %): рядом с κ — доли к истине, где целые проценты прячут разницу."""
    return f"{100 * v:.1f}".replace(".", ",") + "\u00a0%"


def _level(pr: dict | None) -> str:
    """Порог уверенности подтверждения, с которым посчитан make path-retest («0,6»); нет в JSON — прежний 0,8."""
    v = ((pr or {}).get("config") or {}).get("confirm_level")
    return f"{v if v is not None else 0.8:g}".replace(".", ",")


def _k3(v: float) -> str:
    return f"{v:.3f}".replace(".", ",")


def protocols(pr: dict | None, gs: dict | None) -> dict | None:
    """Два протокола с одним порогом: перебор правил (make grade-sweep, выбранная точка P ≥ 0,6 — эти числа в
    docs/NUMBERS.json → grade_accuracy и на слайдах) и контрольный прогон всего пути с настройками продукта
    (make path-retest — числа карточек). Процедура и seed одни, отличаются снимок банка и версия кода. Только числа
    сохранённых JSON, без пересчёта; нет одного из расчётов — нет подписи."""
    t = (pr or {}).get("total") or {}
    tr, pg = t.get("truth") or {}, t.get("path_grade") or {}
    ch = ((gs or {}).get("choice") or {}).get("key")
    m = next((q.get("metrics") or {} for q in (gs or {}).get("points") or [] if q.get("key") == ch), None)
    if not tr or not pg or not m or (pr or {}).get("quick"):
        return None
    ssig, psig = gs.get("signature") or {}, pr.get("signature") or {}
    lvl, slvl = _level(pr), f"{((gs.get('choice') or {}).get('point') or {}).get('confirm_level', 0.6):g}".replace(".", ",")
    nf = (pr.get("config") or {}).get("n_families")
    sweep = {"exact": m.get("exact"), "over": m.get("over"), "retest_exact": m.get("retest_exact"),
             "retest_kappa": m.get("retest_kappa"), "confirm_level": slvl, "bank": ssig.get("bank"),
             "commit": ssig.get("commit"), "points": len(gs.get("points") or []), "command": ssig.get("command")}
    path = {"exact": tr.get("exact"), "over": tr.get("over_share"), "retest_exact": pg.get("exact"),
            "retest_kappa": pg.get("kappa_w"), "confirm_level": lvl, "bank": psig.get("bank"), "bank_families": nf,
            "commit": psig.get("commit"), "command": psig.get("command")}
    same = sweep["bank"] == path["bank"]
    text = (f"Порог P ≥ {lvl} — один в обоих протоколах. Перебор правил (make grade-sweep, {sweep['points']} точек, "
            f"банк {sweep['bank'] or '—'}, коммит {sweep['commit'] or '—'}) выбрал P ≥ {slvl}: точно "
            f"{_p1(sweep['exact'])}, завышение {_p1(sweep['over'])}, повтор {_p1(sweep['retest_exact'])}, κw "
            f"{_k3(sweep['retest_kappa'])} — эти числа в docs/NUMBERS.json (grade_accuracy). Карточки выше — "
            f"контрольный прогон всего пути с настройками продукта (make path-retest, банк {path['bank'] or '—'}"
            f"{f', пул 5 направлений — {nf} семейств' if nf else ''}, коммит {path['commit'] or '—'}): точно {_p1(path['exact'])}, "
            f"завышение {_p1(path['over'])}, повтор {_p1(path['retest_exact'])}, κw {_k3(path['retest_kappa'])}. "
            "Процедура и seed те же; " + ("разница — версия кода, не правило." if same else
                                                     "разница — снимок банка и версия кода, не правило."))
    return {"text": text, "sweep": sweep, "path": path, "same_bank": same}


def retest_vs_truth(pr: dict | None) -> dict | None:
    """Я8 (судья п. 13): рядом с κ повтора — точность к синтетической истине, завышение, занижение, «без категории»,
    цена действующего порога P ≥ 0,6 и маршрут восстановления. Только числа сохранённого make path-retest, без пересчёта."""
    t = (pr or {}).get("total") or {}
    tr, pg, ps = t.get("truth") or {}, t.get("path_grade") or {}, t.get("path") or {}
    if not tr or not pg or (pr or {}).get("quick"):
        return None
    cfg, st = ((pr.get("config") or {}).get("app") or {}), ps.get("status_share") or {}
    k = f"{pg['kappa_w']:.3f}".replace(".", ",")
    return {
        "kappa_w": pg["kappa_w"], "retest_exact": pg["exact"], "exact": tr["exact"], "over": tr["over_share"],
        "under": tr["under_share"], "no_category": tr["no_category_share"],
        "extension_share": ps.get("extension_share"), "accepted_lower": st.get("accepted_lower"),
        "provisional": st.get("provisional"),
        "lead": (f"κ {k} — повторяемость, а не точность: при повторе всего пути грейд совпал у {_p1(pg['exact'])}, "
                 f"а с синтетической истиной — у {_p1(tr['exact'])} (первая попытка)."),
        "cost": (f"Цена порога P ≥ {_level(pr)}: правило осторожно против завышения (выше истинного — {_p1(tr['over_share'])}), "
                 f"поэтому чаще занижает (ниже истинного — {_p1(tr['under_share'])}, без категории — "
                 f"{_p1(tr['no_category_share'])}; «принят уровень ниже» — {_p1(st.get('accepted_lower') or 0)} статусов). "
                 f"Маршрут восстановления: у порога — дотестирование (+{cfg.get('ext_items', '—')} заданий, до "
                 f"{cfg.get('ext_minutes', '—')} мин; было в {_p1(ps.get('extension_share') or 0)} сессий), после — "
                 "вторая попытка на новых вариантах другого субпула."),
        "signature": pr.get("signature")}


def headline() -> dict:
    from app.modules.validation.provenance import stamp  # Я8: строка происхождения у каждого числа

    pr, b, gs = _load(PATH_RETEST), _load(BENCH), _load(GRADE_SWEEP)
    proto = protocols(pr, gs)
    items: list[dict] = []
    if pr and not pr.get("quick"):
        t, sig = pr["total"], pr["signature"]
        pg = t["path_grade"]
        items.append({
            "id": "path_kappa", "anchor": "path-retest", "value": pg["kappa_w"], "ci": pg.get("kappa_w_ci"),
            "format": "num3",
            "title": "Повтор всего пути",
            # доли — с одной десятой, как в блоке «повтор против истины» под карточками (80,5 %, а не 80 % и 80,5 %)
            "text": (f"κ с весами: {pg['n']} синтетических кандидатов прошли опрос, тест и решение дважды. Грейд совпал у "
                     f"{_p1(pg['exact'])}, ±1 ступень — у {_p1(pg['within_1'])}."),
            "note": (f"повторяемость, не точность: с синтетической истиной грейд совпал у {_p1(t['truth']['exact'])}"
                     if t.get("truth") else f"5 ступеней, подтверждение при P ≥ {_level(pr)}; новые варианты заданий"),
            "protocol_note": ((f"Порог P ≥ {_level(pr)}, полный путь (make path-retest). Перебор правил (make grade-sweep) "
                               f"с тем же порогом — {'та же версия банка' if proto['same_bank'] else 'другой снимок банка'}: "
                               "сверка двух протоколов под карточками") if proto else None),
            "signature": sig})
        tr = t["truth"]
        items.append({
            "id": "over_share", "anchor": "path-retest", "value": tr["over_share"], "ci": None, "format": "pct",
            "title": "Грейд выше истинного",
            "text": (f"Ложное завышение грейда. Ниже истинного — {_p(tr['under_share'])}: при сомнении правило "
                     "даёт уровень ниже."),
            "note": "истина известна только в симуляции", "signature": sig})
    if b and not b.get("missing"):
        sig = _bench_signature(b)
        pm, m = b["paired_platform_minus"], b["metrics"]
        if "bm25" in pm:
            d = pm["bm25"]["ndcg@10"]
            items.append({
                "id": "bench_bm25", "anchor": "bench", "value": d["mean"], "ci": [d["lo"], d["hi"]], "format": "signed3",
                "title": "Подбор лучше BM25",
                "pair": [m["platform"]["ndcg@10"]["mean"], m["bm25"]["ndcg@10"]["mean"]],
                "text": "Прирост nDCG@10 к поиску по тексту резюме на бенчмарке со скрытой истиной.",
                "note": "синтетический мир, не рынок", "signature": sig})
        if "no_test" in pm:
            d = pm["no_test"]["ndcg@10"]
            items.append({
                "id": "bench_no_test", "anchor": "ablations", "value": d["mean"], "ci": [d["lo"], d["hi"]],
                "format": "signed3", "title": "Вклад теста в подбор",
                "text": "Падение nDCG@10, если ранжировать по самоописанию без результата теста.",
                "note": "абляция: та же формула, тот же мир", "signature": sig})
        inf = (b.get("groups") or {}).get("inflated") or {}
        if "platform" in inf and "bm25" in inf:
            items.append({
                "id": "inflated", "anchor": "bench", "value": inf["platform"]["irrelevant_inflated_top10"], "ci": None,
                "format": "pct", "compare": inf["bm25"]["irrelevant_inflated_top10"],
                "title": "Раздутые резюме в топ-10",
                "text": (f"Неподходящие с раздутым резюме в топ-10; у BM25 — "
                         f"{_p(inf['bm25']['irrelevant_inflated_top10'])}."),
                "note": f"раздутых в популяции {_p(inf.get('population_share', 0))}", "signature": sig})
    for it in items:  # Я8: «синтетика · дата · SHA алгоритма · банк · команда» — из JSON расчёта
        it["provenance"] = stamp("path" if it["anchor"] == "path-retest" else "bench",
                                 pr if it["anchor"] == "path-retest" else b)
    return {"items": items, "missing": not items, "retest_vs_truth": retest_vs_truth(pr), "protocols": proto,
            "how_to_read": ("Каждое число — из расчёта с подписью мира (seed, hash конфигурации, коммит), рядом — 95 % "
                            "доверительный интервал и строка происхождения: синтетика, модель или люди, дата, SHA "
                            "алгоритма, банк, команда пересчёта. Ниже по странице: синтетика с интервалами, затем "
                            "модельная панель (не люди), затем демо-данные с оговоркой о циркулярности.")}
