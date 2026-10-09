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


def headline() -> dict:
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
            "note": "5 ступеней, подтверждение при P ≥ 0,8; новые варианты заданий",
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
    return {"items": items, "missing": not items,
            "how_to_read": ("Каждое число — из расчёта с подписью мира (seed, hash конфигурации, коммит), рядом — 95 % "
                            "доверительный интервал. Ниже по странице: синтетика с интервалами, затем экспертная "
                            "разметка, затем демо-данные с оговоркой о циркулярности.")}
