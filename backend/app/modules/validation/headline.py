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


def retest_vs_truth(pr: dict | None) -> dict | None:
    """Я8 (судья п. 13): рядом с κ повтора — точность к синтетической истине, завышение, занижение, «без категории»,
    цена порога P ≥ 0,8 и маршрут восстановления. Только числа сохранённого make path-retest, без пересчёта."""
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
        "cost": (f"Цена порога P ≥ 0,8: правило осторожно против завышения (выше истинного — {_p1(tr['over_share'])}), "
                 f"поэтому чаще занижает ({_p1(tr['under_share'])}, без категории — {_p1(tr['no_category_share'])}); "
                 f"восстановление — дотестирование у порога (+{cfg.get('ext_items', '—')} заданий, до "
                 f"{cfg.get('ext_minutes', '—')} мин; было у {_p1(ps.get('extension_share') or 0)} путей), «принять "
                 f"доказанный уровень ниже» без нового теста ({_p1(st.get('accepted_lower') or 0)}) или вторая попытка "
                 "на новых вариантах другого субпула."),
        "signature": pr.get("signature")}


def headline() -> dict:
    from app.modules.validation.provenance import stamp  # Я8: строка происхождения у каждого числа

    pr, b = _load(PATH_RETEST), _load(BENCH)
    items: list[dict] = []
    if pr and not pr.get("quick"):
        t, sig = pr["total"], pr["signature"]
        pg = t["path_grade"]
        items.append({
            "id": "path_kappa", "anchor": "path-retest", "value": pg["kappa_w"], "ci": pg.get("kappa_w_ci"),
            "format": "num3",
            "title": "Повтор всего пути",
            "text": (f"κ с весами: {pg['n']} синтетических кандидатов прошли опрос, тест и решение дважды. Грейд совпал у "
                     f"{_p(pg['exact'])}, ±1 ступень — у {_p(pg['within_1'])}."),
            "note": (f"повторяемость, не точность: с синтетической истиной грейд совпал у {_p1(t['truth']['exact'])}"
                     if t.get("truth") else "5 ступеней, подтверждение при P ≥ 0,8; новые варианты заданий"),
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
    return {"items": items, "missing": not items, "retest_vs_truth": retest_vs_truth(pr),
            "how_to_read": ("Каждое число — из расчёта с подписью мира (seed, hash конфигурации, коммит), рядом — 95 % "
                            "доверительный интервал и строка происхождения: синтетика, модель или люди, дата, SHA "
                            "алгоритма, банк, команда пересчёта. Ниже по странице: синтетика с интервалами, затем "
                            "модельная панель (не люди), затем демо-данные с оговоркой о циркулярности.")}
