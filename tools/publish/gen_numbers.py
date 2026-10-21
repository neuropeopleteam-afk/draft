#!/usr/bin/env python3
"""Генератор единого источника цифр проекта «Драфт»: docs/NUMBERS.json и его копия frontend/src/data/numbers.json.

Правило (А4, 21.10.2026): в этом файле НЕТ ни одного числа-константы. Каждая цифра берётся из JSON-артефакта,
созданного командой пересчёта, и публикуется вместе с условием (что измерено, на ком — модель или люди, N, дата,
команда пересчёта, ссылка на код). Нет артефакта — нет блока (null), а не «значение по умолчанию».

Источники:
- банк заданий — backend/assessment_bank/BANK_SYNC.json (отчёт валидатора на 20 зёрнах);
- вердикт по грейду — backend/app/modules/validation/data/product_sim_*.json (симуляция ПРОДУКТА, А4);
- «Обмани тест» — backend/app/modules/validation/data/cheat_bots.json (боты через движок, А4);
- подбор — docs/realdata/numbers_matching.json (А5), иначе validation/data/matching_bench.json и hh_match.json;
- античит — backend/app/modules/validation/data/grader_numbers.json (А6);
- протоколы ФСП — docs/realdata/fsp_protocols/index_stats.json, ocr_audit.json (А8);
- нагрузка — docs/perf/load.json (А12); мутационный контроль банка — docs/bank/mutation_report.json (А3).

Запуск:  python3 tools/publish/gen_numbers.py [--check]
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "backend" / "app" / "modules" / "validation" / "data"
BANK_SYNC = ROOT / "backend" / "assessment_bank" / "BANK_SYNC.json"
OUT = ROOT / "docs" / "NUMBERS.json"
FRONTEND_OUT = ROOT / "frontend" / "src" / "data" / "numbers.json"
A5_MATCHING = ROOT / "docs" / "realdata" / "numbers_matching.json"
A6_ANTICHEAT = DATA / "grader_numbers.json"
A3_MUTATION = ROOT / "docs" / "bank" / "mutation_report.json"
A8_DIR = ROOT / "docs" / "realdata" / "fsp_protocols"
A12_LOAD = ROOT / "docs" / "perf" / "load.json"
PS = {  # артефакты симуляции продукта (А4): отчётные — только на TEST_SEEDS
    "main": DATA / "product_sim_test_calibrated.json",
    "misspec": DATA / "product_sim_test_misspec.json",
    "rater": DATA / "product_sim_test_rater_noise.json",
    "selection": DATA / "product_sim_train_selection.json",
}
CHEAT = DATA / "cheat_bots.json"
GRADE_RU = {"none": "ниже Intern", "intern": "Intern", "junior": "Junior", "middle": "Middle", "senior": "Senior",
            "lead": "Lead", "principal": "Principal"}


# ---------------------------------------------------------------- утилиты

def _load(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def pct(v: float | None, d: int = 1) -> str:
    return "—" if v is None else f"{100 * float(v):.{d}f}".replace(".", ",")


def num(v: float | None, d: int = 2) -> str:
    return "—" if v is None else f"{float(v):.{d}f}".replace(".", ",")


def int_ru(v: int | None) -> str:
    return "—" if v is None else f"{int(v):,}".replace(",", "\u202f")


def _date(s: str | None) -> str | None:
    return str(s)[:10] if s else None


def replace_block(text: str, name: str, body: str) -> tuple[str, bool]:
    """Заменяет содержимое между <!-- name:begin --> и <!-- name:end --> (для README); идемпотентно."""
    rx = re.compile(rf"(<!-- {re.escape(name)}:begin -->\n)(.*?)(<!-- {re.escape(name)}:end -->)", re.S)
    if not rx.search(text):
        return text, False
    return rx.sub(lambda m: m.group(1) + body.rstrip("\n") + "\n" + m.group(3), text), True


def parse_log(p: Path) -> dict:
    """Итог pytest из лога: passed/skipped/failed, покрытие, код выхода."""
    t = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""

    def g(rx, cast=int):
        m = re.search(rx, t)
        return cast(m.group(1)) if m else None

    cov = g(r"Total coverage: ([\d.]+)%", float)
    return {"passed": g(r"(\d+) passed") or 0, "skipped": g(r"(\d+) skipped") or 0, "failed": g(r"(\d+) failed") or 0,
            "coverage_pct": round(cov, 1) if cov is not None else None, "exit": g(r"EXIT=(\d+)")}


def static_numbers() -> dict:
    """Числа из конфигурации репозитория: лимиты памяти контейнеров (docker-compose.yml) и головы миграций."""
    comp = (ROOT / "docker-compose.yml").read_text(encoding="utf-8") if (ROOT / "docker-compose.yml").exists() else ""
    limits, svc = {}, None
    for line in comp.splitlines():
        m = re.match(r"^  ([a-z0-9_-]+):\s*$", line)
        if m:
            svc = m.group(1)
        m = re.search(r"mem_limit:\s*\"?(\d+)([mMgG])", line) or re.search(r"memory:\s*\"?(\d+)([mMgG])", line)
        if m and svc:
            limits[svc] = int(m.group(1)) * (1024 if m.group(2).lower() == "g" else 1)
    revs, downs = set(), set()
    for f in (ROOT / "backend" / "migrations" / "versions").glob("*.py"):
        s = f.read_text(encoding="utf-8", errors="replace")
        r = re.search(r"^revision\s*[:=][^\n]*?['\"]([^'\"]+)['\"]", s, re.M)
        if r:
            revs.add(r.group(1))
        d = re.search(r"^down_revision\s*[:=]\s*(.+)$", s, re.M)
        if d:
            downs.update(re.findall(r"['\"]([^'\"]+)['\"]", d.group(1)))
    return {"memory_limits_mib": limits, "migrations": {"heads": sorted(revs - downs)}}


def frac(d: dict | None) -> dict | None:
    if not isinstance(d, dict) or d.get("value") is None:
        return None
    return {"value": d["value"], "k": d.get("k"), "n": d.get("n"), "ci95": d.get("ci95")}


# ---------------------------------------------------------------- блоки

def _bank_formats() -> dict:
    """Число семейств с кодом и развёрнутыми ответами — по самим спецификациям банка (не константа)."""
    try:
        sys.path.insert(0, str(ROOT / "backend"))
        from assessment_bank import load_specs

        specs = [s for s in load_specs().values() if not s.canary]
        code = {"find_bug", "predict_output", "choose_fix", "open_answer", "open_book_3step", "incident_sim"}
        return {"code_and_open_families": sum(1 for s in specs if s.format in code), "families_live": len(specs)}
    except Exception:
        return {}


def bank_block() -> dict | None:
    b = _load(BANK_SYNC)
    if not b:
        return None
    s = (b.get("validation") or {}).get("summary") or {}
    return {**_bank_formats(),
        "families": b.get("n_families"),
        "directions": len(b.get("directions_verified") or []),
        "variants_20seeds": s.get("n_variants_generated"),
        "unique_variants_20seeds": s.get("n_unique_variants"),
        "seeds": s.get("n_seeds"),
        "fail": s.get("n_fail"),
        "checks": s.get("n_checks"),
        "checks_failed": s.get("n_checks_failed"),
        "status": s.get("status"),
        "bank_commit": b.get("commit"),
        "content_hash": b.get("content_hash"),
        "synced_at": b.get("synced_at"),
        "recompute": "cd backend && python -m assessment_bank validate --seeds 20",
        "code_ref": "backend/assessment_bank/BANK_SYNC.json",
    }


def _ps_view(d: dict) -> dict:
    s = d.get("summary") or {}
    m = d.get("meta") or {}
    out = {
        "n": s.get("n"),
        "verdict_accuracy": frac(s.get("verdict_accuracy_final")),
        "false_confirm": frac(s.get("false_confirm_among_overclaim")),
        "false_reject": frac(s.get("false_reject_among_true")),
        "confident_share": frac(s.get("confident_share_main")),
        "confident_accuracy": frac(s.get("confident_accuracy_main")),
        "followup_share": frac(s.get("followup_share")),
        "exact_grade": frac(s.get("exact_grade_final")),
        "exact_grade_not_above_claim": frac(s.get("exact_grade_final_not_above_claim")),
        "gross_error": frac(s.get("gross_error_2plus")),
        "minutes_main": s.get("minutes_main"),
        "minutes_total": s.get("minutes_total"),
        "items_main": s.get("items_main"),
        "code_open_share": s.get("code_open_share_main"),
        "integrity_low_share_honest": frac(s.get("integrity_low_share_honest")),
        "engine_errors": (d.get("engine_errors") or {}).get("n"),
        "by_claim": d.get("by_claim"),
        "world": m.get("world"),
        "seeds": m.get("seeds"),
        "bank_families": (m.get("bank") or {}).get("n_families"),
        "settings": m.get("settings"),
        "git_commit": m.get("git_commit"),
        "date": _date(m.get("date")),
        "command": m.get("command"),
    }
    if d.get("retest"):
        r = d["retest"]
        out["retest"] = {"n_pairs": r.get("n_pairs"), "kappa_w": r.get("kappa_w_quadratic"),
                         "exact_agreement": frac(r.get("exact_agreement")),
                         "verdict_agreement": frac(r.get("verdict_agreement")),
                         "shared_families_mean": r.get("shared_families_mean")}
    return out


def grade_verdict_block() -> dict | None:
    main = _load(PS["main"])
    if not main:
        return None
    v = _ps_view(main)
    mis = _load(PS["misspec"])
    rater = _load(PS["rater"])
    sel = _load(PS["selection"])
    va, fc, cs, ca = v["verdict_accuracy"], v["false_confirm"], v["confident_share"], v["confident_accuracy"]
    ex = v["exact_grade"]
    mm, mt = v["minutes_main"] or {}, v["minutes_total"] or {}
    claim = (
        f"Симуляция продукта (движок стенда на банке из {int_ru(v['bank_families'])} семейств; модельные кандидаты, "
        f"не люди; N = {int_ru(v['n'])}, отложенные зёрна): итоговый вердикт «соответствует заявленному грейду» верен в "
        f"{pct(va and va['value'])} % (95 % ДИ {pct(va and va['ci95'][0])}–{pct(va and va['ci95'][1])} %), ложное "
        f"подтверждение у завысивших заявку — {pct(fc and fc['value'])} %; после основной части уверенное решение у "
        f"{pct(cs and cs['value'])} % кандидатов, из них верных {pct(ca and ca['value'])} %; остальным предлагается "
        f"короткий второй этап у порога. Точный грейд — {pct(ex and ex['value'])} %. Время основной части — в среднем "
        f"{num(mm.get('mean'), 0)} мин (p90 {num(mm.get('p90'), 0)}), всего — {num(mt.get('mean'), 0)} мин."
    )
    out = {
        "what": "Симуляция продукта: тот же движок, что на стенде (выбор заданий, остановка, дотестирование, вердикт, "
                "второй этап), на реальном банке; кандидаты — модельные, не люди.",
        "main": v,
        "misspec": _ps_view(mis) if mis else None,
        "rater_noise": _ps_view(rater) | {"noise": (rater.get("meta") or {}).get("rater_noise_text_parts")} if rater else None,
        "selection": sel or None,
        "claim_ru": claim,
        "recompute": v["command"],
        "code_ref": "backend/app/modules/validation/product_sim.py",
        "protocol": "docs/validation/PRODUCT_SIM_PROTOCOL.md",
    }
    return out


def cheat_block() -> dict | None:
    d = _load(CHEAT)
    if not d:
        return None
    t = d.get("table") or {}
    m = d.get("meta") or {}
    worst = max(((k, v) for k, v in t.items() if k != "control"),
                key=lambda kv: (kv[1].get("false_confirmed") or {}).get("value") or 0, default=(None, None))
    ctrl = (t.get("control") or {}).get("false_confirmed") or {}
    claim = None
    if worst[0]:
        w = worst[1]["false_confirmed"]
        claim = (f"Боты-стратегии через движок продукта ({len(t)} стратегий × {m.get('n_per_strategy')} попыток, "
                 f"реальные варианты и проверка ответа): самая успешная стратегия «{worst[0]}» получила подтверждение "
                 f"заявленного грейда в {pct(w.get('value'))} % попыток (95 % ДИ {pct((w.get('ci95') or [None, None])[0])}–"
                 f"{pct((w.get('ci95') or [None, None])[1])} %); контроль — честный кандидат на 0,75 логита ниже порога — "
                 f"{pct(ctrl.get('value'))} %.")
    return {"table": t, "meta": m, "worst_strategy": worst[0], "claim_ru": claim,
            "recompute": m.get("command"), "code_ref": "backend/app/modules/validation/cheat_bots.py"}


def matching_block() -> dict | None:
    a5 = _load(A5_MATCHING)
    if a5.get("matching"):
        return a5["matching"]
    b = _load(DATA / "matching_bench.json")
    if not b:
        return None
    pl = (b.get("metrics") or {}).get("platform") or {}
    sig = b.get("signature") or {}
    w = b.get("world") or {}
    return {
        "world": sig.get("world"), "n_needs": w.get("n_needs"), "n_candidates": w.get("n_candidates"),
        "seed": sig.get("seed"), "bench_commit": sig.get("commit"), "generated_at": b.get("generated_at"),
        "p5": pl.get("p@5"), "p10": pl.get("p@10"), "mrr": pl.get("mrr"), "ndcg10": pl.get("ndcg@10"),
        "recall30": pl.get("recall@30"),
        "what": "бенчмарк подбора: синтетический мир со скрытой истиной (модельные кандидаты, не люди)",
        "recompute": "cd backend && python -m app.modules.validation.matching_bench",
        "code_ref": "backend/app/modules/validation/matching_bench.py",
    }


def hh_block() -> dict | None:
    a5 = _load(A5_MATCHING)
    if a5.get("hh_match"):
        return a5["hh_match"]
    h = _load(DATA / "hh_match.json")
    if not h:
        return None
    o = h.get("overall") or {}
    d, g = o.get("direction_ok") or {}, o.get("grade_ok") or {}
    return {
        "n": h.get("n") or o.get("n"),
        "direction_ok": {"value": d.get("share"), "k": d.get("k"), "n": d.get("n")},
        "grade_ok": {"value": g.get("share"), "k": g.get("k"), "n": g.get("n")},
        "set": "набор разработки (по этим вакансиям настраивался словарь); отложенный набор — после пересчёта А5",
        "what": "разбор реальных вакансий hh.ru: направление и грейд вакансии определены верно",
        "recompute": "python tools/realdata/hh_plus.py match",
        "code_ref": "docs/realdata/HH_MATCH_2660.md",
    }


def anticheat_block() -> dict | None:
    a6 = _load(A6_ANTICHEAT)
    return a6.get("anticheat") or None


def fsp_block() -> dict | None:
    st = _load(A8_DIR / "index_stats.json")
    oc = _load(A8_DIR / "ocr_audit.json")
    agg = _load(A8_DIR / "aggregates.json")
    if not (st or oc or agg):
        return None
    return {"index": st or None, "ocr_audit": oc or None,
            "aggregates_totals": (agg.get("totals") if isinstance(agg, dict) else None),
            "recompute": (st or {}).get("recompute") or "python -m tools.fsp_protocols build",
            "code_ref": "tools/fsp_protocols/"}


def mutation_block() -> dict | None:
    return _load(A3_MUTATION) or None


def load_block() -> dict | None:
    return _load(A12_LOAD) or None


def demo_block() -> dict | None:
    return _load(ROOT / "backend" / "app" / "modules" / "demo" / "seed_stats.json") or None


# ---------------------------------------------------------------- витрина

def landing_cards(bank, gv, matching, hh, fsp) -> list[dict]:
    cards = []
    if bank and bank.get("families"):
        cards.append({
            "id": "bank", "eyebrow": "Банк заданий", "value": int_ru(bank["families"]), "accent": "семейств",
            "subtext": (f"{int_ru(bank.get('variants_20seeds'))} вариантов на {bank.get('seeds')} зёрнах, уникальных — "
                        f"{int_ru(bank.get('unique_variants_20seeds'))} · ошибок генерации — {bank.get('fail')} · "
                        f"{int_ru(bank.get('checks'))} проверок ключей исполнением кода, ошибок — {bank.get('checks_failed')} · "
                        f"{bank.get('directions')} ИТ-направлений"),
            "provenance": f"валидатор банка, {_date(bank.get('synced_at'))}",
            "recompute": bank["recompute"], "code_ref": bank["code_ref"]})
    if gv and gv["main"].get("verdict_accuracy"):
        m = gv["main"]
        va, fc, cs = m["verdict_accuracy"], m["false_confirm"] or {}, m["confident_share"] or {}
        cards.append({
            "id": "grade_verdict", "eyebrow": "Вердикт по заявленному грейду", "value": pct(va["value"]), "accent": "%",
            "subtext": (f"верных решений «подтверждён / не подтверждён» · ложное подтверждение у завысивших — "
                        f"{pct(fc.get('value'))} % · уверенно после основной части — {pct(cs.get('value'))} %, остальным — "
                        f"короткий второй этап · симуляция продукта, N = {int_ru(m['n'])}, модельные кандидаты"),
            "provenance": f"симуляция продукта, {m.get('date')}",
            "recompute": gv["recompute"], "code_ref": gv["code_ref"]})
    if matching and isinstance(matching.get("p5"), dict):
        p5, mrr = matching["p5"], matching.get("mrr") or {}
        cards.append({
            "id": "matching_p5", "eyebrow": "Точность топ-5 подбора (P@5)", "value": pct(p5.get("mean")), "accent": "%",
            "subtext": (f"MRR {num(mrr.get('mean'))} · 95 % ДИ {pct(p5.get('lo'))}–{pct(p5.get('hi'))} % · бенчмарк: "
                        f"{matching.get('n_needs')} потребностей × {int_ru(matching.get('n_candidates'))} кандидатов "
                        f"(синтетический мир, seed {matching.get('seed')})"),
            "provenance": f"бенчмарк подбора, {_date(matching.get('generated_at'))}",
            "recompute": matching["recompute"], "code_ref": matching["code_ref"]})
    if fsp and (fsp.get("index") or {}).get("documents"):
        ix = fsp["index"]
        bits = [f"{int_ru(ix.get('results'))} результатов" if ix.get("results") is not None else None,
                f"{int_ru(ix.get('athletes'))} спортсменов" if ix.get("athletes") is not None else None,
                f"{ix.get('regions')} регионов" if ix.get("regions") is not None else None,
                (f"норматив разряда по ЕВСК подтверждён протоколом у {ix.get('athletes_with_evsk_norm')}"
                 if ix.get("athletes_with_evsk_norm") is not None else None)]
        cards.append({
            "id": "fsp_protocols", "eyebrow": "Официальные протоколы ФСП", "value": str(ix["documents"]),
            "accent": "документов",
            "subtext": " · ".join(b for b in bits if b) + " — кандидат находит своё достижение в официальном протоколе, "
                       "подтверждение — через ФСП",
            "provenance": f"индекс протоколов, {_date(ix.get('generated_at'))}",
            "recompute": fsp["recompute"], "code_ref": fsp["code_ref"]})
    if hh and (hh.get("direction_ok") or {}).get("value") is not None:
        d, g = hh["direction_ok"], hh.get("grade_ok") or {}
        cards.append({
            "id": "hh_real", "eyebrow": "Реальные вакансии hh.ru", "value": int_ru(hh.get("n")), "accent": "вакансий",
            "subtext": (f"направление вакансии определено верно в {pct(d.get('value'))} % ({d.get('k')} из {d.get('n')}), "
                        f"грейд — в {pct(g.get('value'))} % ({g.get('k')} из {g.get('n')}); {hh.get('set') or ''}").rstrip("; "),
            "provenance": "разбор вакансий hh.ru",
            "recompute": hh["recompute"], "code_ref": hh["code_ref"]})
    return cards


def recompute_table(bank, gv, cheat, matching, hh, anticheat, fsp, load) -> list[dict]:
    rows = []
    if bank:
        rows.append({"section": "Банк заданий", "metric": f"{int_ru(bank.get('families'))} семейств, ошибок генерации "
                     f"{bank.get('fail')}, проверок ключей {int_ru(bank.get('checks'))}", "sample": f"{bank.get('seeds')} зёрен",
                     "command": bank["recompute"], "code_ref": bank["code_ref"], "artifact": "backend/assessment_bank/BANK_SYNC.json"})
    if gv:
        m = gv["main"]
        rows.append({"section": "Вердикт по грейду (симуляция продукта)",
                     "metric": f"верный вердикт {pct((m['verdict_accuracy'] or {}).get('value'))} %, ложное подтверждение "
                               f"{pct((m['false_confirm'] or {}).get('value'))} %, точный грейд {pct((m['exact_grade'] or {}).get('value'))} %",
                     "sample": f"N = {int_ru(m['n'])}, отложенные зёрна {m.get('seeds')}, модельные кандидаты",
                     "command": gv["recompute"], "code_ref": gv["code_ref"],
                     "artifact": "backend/app/modules/validation/data/product_sim_test_calibrated.json"})
    if cheat and cheat.get("claim_ru"):
        rows.append({"section": "«Обмани тест»: боты через движок", "metric": cheat["claim_ru"],
                     "sample": f"{(cheat.get('meta') or {}).get('n_per_strategy')} попыток на стратегию",
                     "command": cheat["recompute"], "code_ref": cheat["code_ref"],
                     "artifact": "backend/app/modules/validation/data/cheat_bots.json"})
    if matching and isinstance(matching.get("p5"), dict):
        rows.append({"section": "Подбор под потребность (бенчмарк)",
                     "metric": f"P@5 {pct(matching['p5'].get('mean'))} %, MRR {num((matching.get('mrr') or {}).get('mean'))}",
                     "sample": f"{matching.get('n_needs')} × {int_ru(matching.get('n_candidates'))}, синтетический мир",
                     "command": matching["recompute"], "code_ref": matching["code_ref"],
                     "artifact": "backend/app/modules/validation/data/matching_bench.json"})
    if hh:
        rows.append({"section": "Реальные вакансии hh.ru",
                     "metric": f"направление {pct((hh.get('direction_ok') or {}).get('value'))} %, грейд {pct((hh.get('grade_ok') or {}).get('value'))} %",
                     "sample": f"N = {hh.get('n')}; {hh.get('set') or ''}", "command": hh["recompute"],
                     "code_ref": hh["code_ref"], "artifact": "docs/realdata/numbers_matching.json или validation/data/hh_match.json"})
    if anticheat and isinstance(anticheat.get("holdout_offline"), dict):
        ho, lc = anticheat["holdout_offline"], anticheat.get("llm_chain") or {}
        rows.append({"section": "Античит оценщика развёрнутых ответов",
                     "metric": f"слепой набор: фильтр {ho.get('caught')}/{ho.get('total')}, ложные {ho.get('false_positives')}/"
                               f"{ho.get('honest_n')}, полная цепочка с моделью — пробитий {lc.get('pierced')}/{lc.get('total')}",
                     "sample": "атаки от моделей других поставщиков, хэш набора до прогона", "command": anticheat.get("recompute"),
                     "code_ref": anticheat.get("code_ref"), "artifact": "backend/app/modules/validation/data/grader_numbers.json"})
    if fsp and fsp.get("index"):
        rows.append({"section": "Протоколы ФСП", "metric": f"{fsp['index'].get('documents')} документов, "
                     f"{int_ru(fsp['index'].get('results'))} результатов", "sample": "официальные протоколы с сайта ФСП",
                     "command": fsp["recompute"], "code_ref": fsp["code_ref"], "artifact": "docs/realdata/fsp_protocols/index_stats.json"})
    if load:
        rows.append({"section": "Нагрузка", "metric": load.get("claim_ru") or "см. docs/perf/LOAD.md", "sample": load.get("sample") or "",
                     "command": load.get("recompute") or "", "code_ref": "tools/perf/", "artifact": "docs/perf/load.json"})
    return rows


def build() -> dict:
    bank, gv, cheat = bank_block(), grade_verdict_block(), cheat_block()
    matching, hh, anticheat = matching_block(), hh_block(), anticheat_block()
    fsp, mutation, load = fsp_block(), mutation_block(), load_block()
    cards = landing_cards(bank, gv, matching, hh, fsp)
    headline = " · ".join(f"{c['eyebrow']}: {c['value']}{(' ' + c['accent']) if c['accent'] != '%' else ' %'}" for c in cards)
    claims = {k: v for k, v in {
        "provenance": "Каждая цифра на сайте — из JSON-артефакта с командой пересчёта и ссылкой на код (docs/NUMBERS.json).",
        "grade": gv and gv.get("claim_ru"),
        "cheat": cheat and cheat.get("claim_ru"),
        "anticheat": anticheat and anticheat.get("claim_ru"),
    }.items() if v}
    return {
        "$comment": "Единый источник цифр «Драфт». Генерируется tools/publish/gen_numbers.py только из JSON-артефактов; "
                    "констант нет. Модельные расчёты подписаны «модельные кандидаты, не люди».",
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": _git_head(),
        "recompute_all": "python3 tools/publish/gen_numbers.py",
        "bank": bank,
        "grade_verdict": gv,
        "cheat_bots": cheat,
        "matching": matching,
        "hh_match": hh,
        "anticheat": anticheat,
        "fsp_protocols": fsp,
        "mutation_testing": mutation,
        "load": load,
        "demo": demo_block(),
        "landing_cards": cards,
        "jury_banner": {"headline_ru": headline, "claims_ru": claims},
        "recompute_table": recompute_table(bank, gv, cheat, matching, hh, anticheat, fsp, load),
    }


REPORT_MD = ROOT / "docs" / "validation" / "VALIDATION_REPORT.md"


def report_md(n: dict) -> str:
    """docs/validation/VALIDATION_REPORT.md — только из NUMBERS.json (генерируется вместе с ним)."""
    L = ["# Отчёт валидации «Драфт» (генерируется tools/publish/gen_numbers.py из docs/NUMBERS.json)", "",
         f"Коммит {n['git_commit']}, {n['generated_at']}. Чисел, введённых руками, здесь нет.", ""]
    gv = n.get("grade_verdict")
    if gv:
        m = gv["main"]
        L += ["## Решение по заявленному грейду — симуляция продукта", "", gv["what"], "", gv["claim_ru"], "",
              "| Метрика | Значение | 95 % ДИ | k / n |", "|---|---|---|---|"]
        for key, title in [("verdict_accuracy", "Верный итоговый вердикт"), ("false_confirm", "Ложное подтверждение (у завысивших)"),
                           ("false_reject", "Ложный отказ (у соответствующих)"), ("confident_share", "Уверенно после основной части"),
                           ("confident_accuracy", "Точность уверенных решений"), ("followup_share", "Второй этап"),
                           ("exact_grade", "Точный грейд"), ("gross_error", "Ошибка на 2+ ступени")]:
            f = m.get(key)
            if f:
                c = f.get("ci95") or [None, None]
                L.append(f"| {title} | {pct(f['value'])} % | {pct(c[0])}–{pct(c[1])} % | {f.get('k')} / {f.get('n')} |")
        if m.get("retest"):
            r = m["retest"]
            L += ["", f"Повторяемость (две независимые попытки, пар {r['n_pairs']}): тот же грейд — "
                      f"{pct((r.get('exact_agreement') or {}).get('value'))} %, тот же вердикт — "
                      f"{pct((r.get('verdict_agreement') or {}).get('value'))} %, взвешенная каппа {num(r.get('kappa_w'))}."]
        for k, t in [("misspec", "Мир «банк не откалиброван»"), ("rater_noise", "Ошибка проверки развёрнутых ответов")]:
            x = gv.get(k)
            if x:
                L.append(f"- {t}: верный вердикт {pct((x.get('verdict_accuracy') or {}).get('value'))} %, ложное подтверждение "
                         f"{pct((x.get('false_confirm') or {}).get('value'))} %, точный грейд {pct((x.get('exact_grade') or {}).get('value'))} % "
                         f"(N = {x.get('n')}).")
        sel = gv.get("selection") or {}
        if sel.get("rows"):
            L += ["", f"Выбор настроек на обучающих зёрнах ({sel.get('rule')}); выбрано {sel.get('chosen')}:", "",
                  "| Конфигурация | Верный вердикт | Ложное подтв. | p90 основной, мин |", "|---|---|---|---|"]
            for r in sel["rows"]:
                L.append(f"| {r['config']} — {r['desc']} | {pct(r['verdict_accuracy'])} % | {pct(r['false_confirm'])} % | {r['minutes_main_p90']} |")
        L += ["", f"Пересчёт: `{gv['recompute']}`. Протокол: `{gv['protocol']}`.", ""]
    cb = n.get("cheat_bots")
    if cb:
        L += ["## «Обмани тест»: боты через движок", "", cb.get("claim_ru") or "", "",
              "| Стратегия | Попыток | Грейд подтверждён | 95 % ДИ |", "|---|---|---|---|"]
        for k, r in (cb.get("table") or {}).items():
            f = r["false_confirmed"]
            c = f.get("ci95") or [None, None]
            L.append(f"| {k} | {r['n']} | {pct(f['value'])} % ({f['k']}) | {pct(c[0])}–{pct(c[1])} % |")
        L += ["", f"Пересчёт: `{cb.get('recompute')}`.", ""]
    L += ["## Все цифры сайта и команды пересчёта", "", "| Раздел | Цифра | Выборка | Команда |", "|---|---|---|---|"]
    for r in n.get("recompute_table") or []:
        L.append(f"| {r['section']} | {r['metric']} | {r['sample']} | `{r['command']}` |")
    return "\n".join(L) + "\n"


def _strip(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in ("generated_at", "git_commit")}


def main() -> int:
    new = build()
    if "--check" in sys.argv:
        if _strip(_load(OUT)) != _strip(json.loads(json.dumps(new, ensure_ascii=False))):
            print("NUMBERS.json устарел — запустите tools/publish/gen_numbers.py", file=sys.stderr)
            return 1
        print("NUMBERS.json актуален")
        return 0
    txt = json.dumps(new, ensure_ascii=False, indent=2) + "\n"
    OUT.write_text(txt, encoding="utf-8")
    FRONTEND_OUT.parent.mkdir(parents=True, exist_ok=True)
    FRONTEND_OUT.write_text(txt, encoding="utf-8")
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(report_md(new), encoding="utf-8")
    print(f"Записано {OUT.relative_to(ROOT)}, {FRONTEND_OUT.relative_to(ROOT)} и {REPORT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
