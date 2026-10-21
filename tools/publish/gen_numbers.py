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
# Поправка №2 (21.10 вечер): итоговые прогоны на замороженном банке — жёсткие условия и стандартные условия (S-T)
PS_FINAL = {"hard": DATA / "product_sim_final_calibrated.json", "misspec": DATA / "product_sim_final_misspec.json",
            "rater": DATA / "product_sim_final_rater_noise.json", "amult07": DATA / "product_sim_final_amult07.json",
            "amult14": DATA / "product_sim_final_amult14.json", "testlet": DATA / "product_sim_final_testlet.json",
            "fatigue": DATA / "product_sim_final_fatigue.json"}
# Поправка №3: одна строка S-T — параметры А15 (a = 1,5; истина a × U(0,825; 1,175), b + N(0; 0,3); c 0,25 / 0,02;
# θ ~ N(0,5; 1,0); заявки 65/25/10)
PS_ST = {"st": DATA / "product_sim_st.json"}
DJINNI = ROOT / "docs" / "realdata" / "djinni" / "external_djinni.json"  # А17: внешний открытый набор (подбор)
TRAIN_CHOICE = ROOT / "docs" / "validation" / "TRAIN_CHOICE_2110b.json"  # выбор конфигурации на TRAIN (поправка №3)
# Пятёрка первого экрана (поправка №3): точность уверенного — всегда парой с долей уверенных; точный грейд — по всем
# кандидатам и 6 ступеням, рядом строки 5 и 4 ступеней (сопоставимость) и «среди тех, кому продукт его определяет»;
# ±1 — с числом грубых ошибок (2+ ступени); повтор — κw с ДИ, совпадение грейда и решения
TOP5 = (("confident_accuracy", "Точность уверенного вердикта", "confident_accuracy_final"),
        ("false_confirm_all", "Ложное подтверждение (от всех)", "false_confirm_all"),
        ("exact_grade", "Точный грейд (6 ступеней, все кандидаты)", "exact_grade_final"),
        ("within_one", "Грейд ±1 ступень", "within_one_final"),
        ("retest_kappa_w", "Повтор теста (κw)", None))
TOP5_PAIRS = {"confident_accuracy": {"confident_share": "confident_share_final"},
              "false_confirm_all": {"among_overclaim": "false_confirm_among_overclaim"},
              "exact_grade": {"grades_5": "exact_grade_final_5", "grades_4": "exact_grade_final_4",
                              "not_underclaim": "exact_grade_final_not_underclaim", "main_part": "exact_grade_main",
                              "main_part_grades_5": "exact_grade_main_5", "main_part_grades_4": "exact_grade_main_4",
                              "above_true": "grade_above_true_final"},
              "within_one": {"gross_error_2plus": "gross_error_2plus"}}
TOP5_PAIRS["exact_grade"]["above_true_5"] = "grade_above_true_final_5"  # для сравнения с аналогичными — по 5 ступеням
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
        m = (re.search(r"mem_limit:\s*\"?(?:\$\{[A-Z_]+:-)?(\d+)([mMgG])", line)
             or re.search(r"memory:\s*\"?(?:\$\{[A-Z_]+:-)?(\d+)([mMgG])", line))
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


def wilson(k: int, n: int) -> list[float] | None:
    """95 % интервал Уилсона для доли k/n (z для 95 % — квантиль нормального распределения, а не подогнанное число)."""
    if not n:
        return None
    from statistics import NormalDist

    z = NormalDist().inv_cdf(0.975)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


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
        # число зёрен валидатора: summary.n_seeds (А3, b642953d1), в старых BANK_SYNC — уровнем выше (validation.seeds / n_seeds)
        "seeds": s.get("n_seeds") or (b.get("validation") or {}).get("n_seeds") or (b.get("validation") or {}).get("seeds"),
        "fail": s.get("n_fail"),
        "checks": s.get("n_checks"),
        "checks_failed": s.get("n_checks_failed"),
        "status": s.get("status"),
        "bank_commit": b.get("commit"),
        "content_hash": b.get("content_hash"),
        "synced_at": b.get("synced_at"),
        "recompute": "cd backend && python -m assessment_bank validate --seeds 20",
        "code_ref": "backend/assessment_bank/BANK_SYNC.json",
        **_bank_quality(b),
    }


def _bank_quality(b: dict) -> dict:
    """Качество банка для сайта и Насти (2б-1): из файлов А3 — метрики банка, валидатор на 100 зёрнах, атаки."""
    bm = _load(ROOT / "docs" / "bank" / "bank_metrics_for_a4.json") or {}
    q = bm.get("quality") or {}
    out: dict = {}
    if bm.get("content_hash") and bm.get("content_hash") != b.get("content_hash"):
        return {"quality_note": "метрики банка А3 — для другого хэша, не показываются"}
    pri = q.get("prior_a_by_format") or {}
    # практические — всё, кроме вопросов с выбором ответа (a = 1,3 до калибровки на людях)
    fams = bm.get("by_direction") or {}
    fmt = {}
    for d in fams.values():
        for k, v in (d.get("formats") or {}).items():
            fmt[k] = fmt.get(k, 0) + int(v)
    if fmt:
        out["formats_total"] = fmt
        out["practical_families"] = sum(v for k, v in fmt.items() if k != "mcq_concept")
        out["choice_families"] = fmt.get("mcq_concept", 0)
    # валидатор на 100 зёрнах — самый свежий файл validation_100_*.json, если в нём тот же или больший банк
    v100 = sorted((ROOT / "docs" / "bank").glob("validation_100_*.json"), key=lambda x: x.stat().st_mtime)
    if v100:
        vs = (_load(v100[-1]) or {}).get("summary") or {}
        out["validation_100"] = {"file": str(v100[-1].relative_to(ROOT)), "families": vs.get("n_families"),
                                 "variants": vs.get("n_variants_generated"), "unique_variants": vs.get("n_unique_variants"),
                                 "checks": vs.get("n_checks"), "checks_failed": vs.get("n_checks_failed"),
                                 "fail": vs.get("n_fail"), "warn": vs.get("n_warn"),
                                 "note_ru": ("валидатор на 100 зёрнах — на дереве банка до перезаморозки (без 2 возвращённых "
                                             "семейств)" if vs.get("n_families") != b.get("n_families") else None)}
    au = q.get("audit") or {}
    ga = (au.get("guess_attack") or {}).get("all_numeric_choice") or {}
    if ga:
        out["guess_without_knowledge"] = {"accuracy": ga.get("best_accuracy"), "chance": ga.get("chance"),
                                          "n_variants": ga.get("n_variants"), "heuristic": ga.get("best_heuristic"),
                                          "source": au.get("file"), "command": au.get("command")}
    if au:
        out["audit"] = {k: au.get(k) for k in ("grade_in_stem", "public_leak", "generation_errors", "n_seeds")}
    pa = _load(ROOT / "docs" / "bank" / "position_attack_2110g_final.json") or {}
    ps = pa.get("summary") or {}
    if ps:
        out["studied_code_attack"] = {
            "chance": ps.get("chance"), "letter": (ps.get("letter") or {}).get("acc"),
            "len_rank": (ps.get("len_rank") or {}).get("acc"), "text": (ps.get("text") or {}).get("acc"),
            "n_families": pa.get("n_families"), "train_seeds": pa.get("train_seeds"), "test_seeds": pa.get("test_seeds"),
            "source": "docs/bank/position_attack_2110g_final.json", "command": pa.get("command"),
            "claim_ru": (f"«Изучивший код» (знает генераторы, учится на {pa.get('train_seeds')} зёрнах, проверка на "
                         f"{pa.get('test_seeds')} других): угадывает букву ответа в {pct(((ps.get('letter') or {}).get('acc')))} % "
                         f"при случайном {pct(ps.get('chance'))} %; по длине варианта — {pct((ps.get('len_rank') or {}).get('acc'))} %, "
                         f"по тексту — {pct((ps.get('text') or {}).get('acc'))} %")}
    mu = q.get("mutation") or {}
    if mu:
        out["mutation"] = {k: mu.get(k) for k in list(mu)[:15] if not isinstance(mu.get(k), (dict, list))}
    return out


def _ps_view(d: dict) -> dict:
    s = d.get("summary") or {}
    m = d.get("meta") or {}
    fco = s.get("false_confirm_among_overclaim") or {}
    n_all = s.get("n")
    false_confirm_all = None
    if fco.get("k") is not None and n_all:
        false_confirm_all = {"value": round(fco["k"] / n_all, 4), "k": fco["k"], "n": n_all, "ci95": wilson(fco["k"], n_all)}
    man = (m.get("bank") or {}).get("manifest") or {}
    out = {
        "n": s.get("n"),
        "verdict_accuracy": frac(s.get("verdict_accuracy_final")),
        "false_confirm_all": false_confirm_all,
        "false_confirm": frac(s.get("false_confirm_among_overclaim")),
        "false_reject": frac(s.get("false_reject_among_true")),
        "confident_share": frac(s.get("confident_share_main")),
        "confident_accuracy": frac(s.get("confident_accuracy_main")),
        "followup_share": frac(s.get("followup_share")),
        "exact_grade": frac(s.get("exact_grade_final")),
        "exact_grade_not_above_claim": frac(s.get("exact_grade_final_not_above_claim")),
        "gross_error": frac(s.get("gross_error_2plus")),
        "within_one": frac(s.get("within_one_final")),
        "exact_grade_5": frac(s.get("exact_grade_final_5")),
        "exact_grade_4": frac(s.get("exact_grade_final_4")),
        "exact_grade_far_0_25": frac((s.get("far_from_cut_0_25") or {}).get("exact_grade_final")),
        "confident_accuracy_final": frac(s.get("confident_accuracy_final")),
        "confident_share_final": frac(s.get("confident_share_final")),
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
        "bank_commit": man.get("commit"),
        "bank_content_hash": man.get("content_hash"),
        "bank_synced_at": _date(man.get("synced_at")),
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
                         "decision_agreement": frac(r.get("decision_agreement")),
                         "kappa_w_ci": r.get("kappa_w_quadratic_ci"),
                         "shared_families_mean": r.get("shared_families_mean")}
    return out


def grade_verdict_block() -> dict | None:
    # итоговый прогон (поправки №2–3) заменяет прежний отчётный TEST: основной — жёсткие условия FINAL
    fin = _load(PS_FINAL["hard"])
    main = fin or _load(PS["main"])
    if not main:
        return None
    v = _ps_view(main)
    mis = _load(PS_FINAL["misspec"]) if fin else _load(PS["misspec"])
    rater = _load(PS_FINAL["rater"]) if fin else _load(PS["rater"])
    sel = _load(TRAIN_CHOICE) if fin else _load(PS["selection"])
    va, fc, cs, ca = v["verdict_accuracy"], v["false_confirm"], v["confident_share"], v["confident_accuracy"]
    ex = v["exact_grade"]
    mm, mt = v["minutes_main"] or {}, v["minutes_total"] or {}
    fa = v["false_confirm_all"]
    rt = v.get("retest") or {}
    bank_now = _load(BANK_SYNC)
    same_bank = bool(bank_now) and bank_now.get("content_hash") == v.get("bank_content_hash")
    bank_condition = (
        f"Прогон — на банке {v.get('bank_commit') or '—'} ({int_ru(v['bank_families'])} семейств, снимок "
        f"{v.get('bank_content_hash') or '—'} от {v.get('bank_synced_at') or '—'}); "
        + ("банк сайта тот же." if same_bank else
           f"банк в репозитории сейчас другой: {bank_now.get('commit') or '—'} ({int_ru(bank_now.get('n_families'))} семейств) — "
           f"цифры относятся к банку прогона.")
    )
    claim = (
        f"Симуляция продукта (движок стенда на банке {v.get('bank_commit') or '—'} из {int_ru(v['bank_families'])} семейств; "
        f"модельные кандидаты, не люди; N = {int_ru(v['n'])}, отложенные зёрна): итоговый вердикт «соответствует "
        f"заявленному грейду» верен в {pct(va and va['value'])} % (95 % ДИ {pct(va and va['ci95'][0])}–"
        f"{pct(va and va['ci95'][1])} %); ложное подтверждение — {pct(fc and fc['value'])} % у завысивших заявку "
        f"({pct(fa and fa['value'])} % всех кандидатов); после основной части уверенное решение у "
        f"{pct(cs and cs['value'])} % кандидатов, из них верных {pct(ca and ca['value'])} %; остальным предлагается "
        f"короткий второй этап у порога. Точный грейд по всему пулу — {pct(ex and ex['value'])} %, ошибок на 2+ ступени — "
        f"{pct(v['gross_error'] and v['gross_error']['value'])} %. Время основной части — в среднем "
        f"{num(mm.get('mean'), 0)} мин (p90 {num(mm.get('p90'), 0)}), всего — {num(mt.get('mean'), 0)} мин"
        + (f"; повторная независимая попытка даёт тот же грейд в {pct((rt.get('exact_agreement') or {}).get('value'))} %, "
           f"тот же вердикт — в {pct((rt.get('verdict_agreement') or {}).get('value'))} % (пар {int_ru(rt.get('n_pairs'))})"
           if rt else "") + "."
    )
    out = {
        "what": "Симуляция продукта: тот же движок, что на стенде (выбор заданий, остановка, дотестирование, вердикт, "
                "второй этап), на реальном банке; кандидаты — модельные, не люди.",
        "main": v,
        "misspec": _ps_view(mis) if mis else None,
        "rater_noise": _ps_view(rater) | {"noise": (rater.get("meta") or {}).get("rater_noise_text_parts")} if rater else None,
        "selection": sel or None,
        "claim_ru": claim,
        "bank_condition_ru": bank_condition,
        "recompute": v["command"],
        "code_ref": "backend/app/modules/validation/product_sim.py",
        "protocol": "docs/validation/PRODUCT_SIM_PROTOCOL.md",
    }
    return out


def _cond_ru(d: dict) -> str:
    """Условие прогона одной строкой (для подписи цифры)."""
    m = d.get("meta") or {}
    s = d.get("summary") or {}
    man = (m.get("bank") or {}).get("manifest") or {}
    pop = m.get("population_kind") or "hard"
    ba = m.get("bank_a_override") or {}
    if m.get("world") == "st":
        cond = (f"стандартные условия (как в аналогичных решениях): a = {num(ba.get('mcq'), 1)} в движке, истинные a × U(0,825; "
                f"1,175) и b + N(0; 0,3), угадывание 0,25 в вопросах с выбором и 0,02 в остальных, θ ~ N(0,5; 1,0), "
                f"заявки: 65 % точные, 25 % завышены, 10 % занижены")
    else:
        cond = ("жёсткие условия: угадывание в вопросах с выбором, завышение и занижение заявок, кандидаты у порогов, "
                f"консервативные параметры банка (a = 1,0 / 1,3)" + ("" if m.get("world") in ("calibrated", None) else
                                                                    f", мир «{m.get('world')}»"))
    mt = s.get("minutes_total") or {}
    return (f"{cond}; модельные кандидаты, не люди; N = {int_ru(s.get('n'))}, зёрна {', '.join(str(x) for x in (m.get('seeds') or [])[:1])}…"
            f"{(m.get('seeds') or [''])[-1]}; время — в среднем {num(mt.get('mean'), 0)} мин (p90 {num(mt.get('p90'), 0)}); "
            f"банк {man.get('commit') or '—'} ({man.get('content_hash') or '—'}), {_date(m.get('date'))}")


def top5_from(d: dict) -> list[dict]:
    """Пять чисел первого экрана из артефакта симуляции продукта (порядок и id фиксированы)."""
    if not d:
        return []
    s = d.get("summary") or {}
    rt = d.get("retest") or {}
    mt = s.get("minutes_total") or {}
    cond = _cond_ru(d)
    out = []
    for iid, label, key in TOP5:
        if key is None:
            kw = rt.get("kappa_w_quadratic")
            if kw is None:
                continue
            ex = rt.get("exact_agreement") or {}
            out.append({"id": iid, "label_ru": label, "value": kw, "display_ru": num(kw, 2), "ci95": None,
                        "k": ex.get("k"), "n": rt.get("n_pairs"), "condition_ru": cond + f"; пар повтора {int_ru(rt.get('n_pairs'))}",
                        "minutes": mt, "recompute": (d.get("meta") or {}).get("command")})
            continue
        f = s.get(key) or {}
        if f.get("value") is None:
            continue
        item = {"id": iid, "label_ru": label, "value": f["value"], "display_ru": pct(f["value"]) + " %",
                "ci95": f.get("ci95"), "k": f.get("k"), "n": f.get("n"), "condition_ru": cond, "minutes": mt,
                "recompute": (d.get("meta") or {}).get("command")}
        pairs = {k: frac(s.get(v)) for k, v in (TOP5_PAIRS.get(iid) or {}).items() if s.get(v)}
        if pairs:
            item["with"] = pairs
        out.append(item)
    for it in out:  # повтор: к κw — ДИ и совпадения (грейд, решение подтверждён / не подтверждён), κ Коэна без весов
        if it["id"] == "retest_kappa_w":
            it["ci95"] = (rt.get("kappa_w_quadratic_ci") or {}).get("ci95")
            it["with"] = {k: v for k, v in {
                "exact_agreement": frac(rt.get("exact_agreement")),
                "decision_agreement": frac(rt.get("decision_agreement")),
                # κ Коэна бинарного решения «подтверждён / нет» между попытками (так считают аналогичные решения)
                "kappa_decision": rt.get("kappa_decision"),
                "kappa_cohen_unweighted": rt.get("kappa_cohen_unweighted"),
                "kappa_w_with_truth": s.get("kappa_w_with_truth_final"),
                "kappa_w_with_truth_4": s.get("kappa_w_with_truth_final_4")}.items() if v}
        if it["id"] == "exact_grade":  # 4 ступени у кандидатов дальше 0,25 от любого порога 0 / 1 / 2
            f4 = (s.get("far_from_cut_0_25_grades4") or {}).get("exact_grade_final_4")
            if f4:
                it.setdefault("with", {})["far_grades4"] = frac(f4)
    return out


def _extra(d: dict) -> dict | None:
    if not d:
        return None
    s = d.get("summary") or {}
    near = [(k, v) for k, v in (s.get("by_distance_claim_cut") or {}).items() if k.startswith("0–0.25")]
    far_rows = [v for k, v in (s.get("by_distance_claim_cut") or {}).items() if not k.startswith("0–0.25")]
    far_k = sum((v.get("verdict_accuracy_final") or {}).get("k") or 0 for v in far_rows)
    far_n = sum((v.get("verdict_accuracy_final") or {}).get("n") or 0 for v in far_rows)
    return {"exact_grade_all": frac(s.get("exact_grade_final")),
            "overclaim_passed": frac(s.get("false_confirm_among_overclaim")),
            "accuracy_near_cut": frac((near[0][1].get("verdict_accuracy_final") if near else None)),
            "accuracy_far_cut": ({"value": round(far_k / far_n, 4), "k": far_k, "n": far_n, "ci95": wilson(far_k, far_n)}
                                 if far_n else None),
            "outside_0_25": s.get("outside_0_25"), "outside_0_4": s.get("outside_0_4"),
            "fixed_vs_adaptive": s.get("fixed_vs_adaptive"), "minutes_total": s.get("minutes_total"),
            "far_from_cut_0_25": s.get("far_from_cut_0_25"),
            "far_from_cut_0_25_grades4": s.get("far_from_cut_0_25_grades4"),
            "retest": {k: (d.get("retest") or {}).get(k) for k in (
                "n_pairs", "kappa_w_quadratic", "kappa_w_quadratic_ci", "kappa_decision", "kappa_cohen_unweighted",
                "exact_agreement", "exact_agreement_5", "exact_agreement_4", "decision_agreement", "within_one_agreement")
                if (d.get("retest") or {}).get(k) is not None} or None,
            "outside_0_25": s.get("outside_0_25"), "outside_0_3": s.get("outside_0_3"),
            "kappa_w_with_truth_final_4": s.get("kappa_w_with_truth_final_4"),
            "grade_above_true_final_5": frac(s.get("grade_above_true_final_5")),
            "confident_accuracy_final": frac(s.get("confident_accuracy_final")),
            "false_confirm_all": frac(s.get("false_confirm_all")), "within_one_final": frac(s.get("within_one_final")),
            "exact_grade_final_5": frac(s.get("exact_grade_final_5")), "exact_grade_final_4": frac(s.get("exact_grade_final_4")),
            "exact_grade_main_5": frac(s.get("exact_grade_main_5")), "exact_grade_main_4": frac(s.get("exact_grade_main_4")),
            "grade_above_true_final": frac(s.get("grade_above_true_final")),
            "grade_below_true_final": frac(s.get("grade_below_true_final")),
            "kappa_w_with_truth_final": s.get("kappa_w_with_truth_final"),
            "kappa_w_with_truth_main": s.get("kappa_w_with_truth_main"),
            "false_reject_all": frac(s.get("false_reject_all")),
            "minutes_main": s.get("minutes_main"), "extended_share": frac(s.get("extended_share")),
            "confident_share_main": frac(s.get("confident_share_main")),
            "confident_accuracy_main": frac(s.get("confident_accuracy_main")),
            "confident_share_final": frac(s.get("confident_share_final")),
            "false_confirm_main_all": frac(s.get("false_confirm_main_all")),
            "exact_grade_main": frac(s.get("exact_grade_main")), "gross_error_2plus": frac(s.get("gross_error_2plus")),
            "followup_share": frac(s.get("followup_share")), "oral_share": frac(s.get("oral_share")),
            "undecided_final": frac(s.get("undecided_final")), "oc_curve": s.get("oc_curve"),
            "by_distance_nearest_cut": s.get("by_distance_nearest_cut"), "condition_ru": _cond_ru(d),
            "recompute": (d.get("meta") or {}).get("command")}


def top5_meta(hard: dict, st: dict) -> dict:
    def one(d):
        if not d:
            return None
        m = d.get("meta") or {}
        man = (m.get("bank") or {}).get("manifest") or {}
        ba = m.get("bank_a_override") or {}
        return {"seeds": m.get("seeds"), "n": (d.get("summary") or {}).get("n"),
                "bank_content_hash": man.get("content_hash"), "bank_commit": man.get("commit"),
                "a_mcq": ba.get("mcq"), "a_code": ba.get("code"), "world": m.get("world"),
                "population": m.get("population"), "date": _date(m.get("date")), "command": m.get("command"),
                "git_commit": m.get("git_commit"), "condition_ru": _cond_ru(d)}
    a, b = one(st), one(hard)
    man = (((hard or st or {}).get("meta") or {}).get("bank") or {}).get("manifest") or {}
    return {"st": a, "hard": b,
            # плоские поля для главной (Landing.tsx: standard_condition_ru / hard_condition_ru, Top5Meta)
            "standard_condition_ru": (a or {}).get("condition_ru"), "hard_condition_ru": (b or {}).get("condition_ru"),
            "bank_hash": man.get("content_hash"), "bank_commit": man.get("commit"),
            "bank_families": man.get("n_families") or (len(man.get("families") or []) or None),
            "n": (b or a or {}).get("n"), "generated_at": (b or a or {}).get("date"),
            "rule_ru": "Заголовок — стандартные условия (как в аналогичных решениях), рядом — те же метрики в жёстких "
                       "условиях; обе строки всегда вместе (решение владельца 21.10, записано до прогонов)."}


def cheat_block() -> dict | None:
    d = _load(CHEAT)
    if not d:
        return None
    t = d.get("table") or {}
    m = d.get("meta") or {}
    # single_form — контрфакт «единая форма на всех» (не стратегия против продукта): в «худшую стратегию» не входит
    worst = max(((k, v) for k, v in t.items() if k not in ("control", "single_form")),
                key=lambda kv: (kv[1].get("false_confirmed") or {}).get("value") or 0, default=(None, None))
    ctrl = (t.get("control") or {}).get("false_confirmed") or {}
    gap = _bot_gap(m)
    claim = None
    if worst[0]:
        w = worst[1]["false_confirmed"]
        sf = (t.get("single_form") or {}).get("false_confirmed") or {}
        claim = (f"Боты-стратегии через движок продукта ({len([k for k in t if k != 'single_form'])} стратегий × "
                 f"{m.get('n_per_strategy')} попыток, реальные варианты и проверка ответа): самая успешная стратегия "
                 f"«{worst[0]}» получила подтверждение заявленного грейда в {pct(w.get('value'))} % попыток (95 % ДИ "
                 f"{pct((w.get('ci95') or [None, None])[0])}–{pct((w.get('ci95') or [None, None])[1])} %); контроль — "
                 f"честный кандидат чуть слабее заявленного уровня (на {num(gap, 1)} по шкале теста) — "
                 f"{pct(ctrl.get('value'))} %"
                 + (f"; единая форма на всех (как у статичных тестов) с утёкшими ответами — подтверждение в "
                    f"{pct(sf.get('value'))} % попыток, а при вариативных формах продукта слепая подстановка утёкших "
                    f"ответов не работает" if sf.get("value") is not None else "") + ".")
    lf = {}
    for key, strat in (("weak_no_leak", "control"), ("weak_leak_10", "leak_10"), ("weak_leak_100", "leak_100"),
                       ("weak_leak_1000", "leak_1000"), ("single_form", "single_form")):
        r = t.get(strat)
        if r:
            f = r.get("false_confirmed") or {}
            lf[key] = {"value": f.get("value"), "k": f.get("k"), "n": r.get("n"), "ci95": f.get("ci95"),
                       # сдвиг оценки уровня θ̂ относительно того же «слабого» без утечки — разность средних с 95 % ДИ
                       "theta_shift_vs_control": r.get("theta_shift_vs_control")}
    return {"table": t, "meta": m, "worst_strategy": worst[0], "claim_ru": claim, "leak_form": lf or None,
            "bot_gap": gap,
            "leak_form_ru": (f"Доля слабых кандидатов (чуть слабее заявленного грейда — на {num(gap, 1)} по шкале теста), "
                             "получивших подтверждение: без утечки, со слепой подстановкой ключей K утёкших вариантов "
                             "каждого семейства (бот подставляет утёкший ответ и там, где вариант другой — наивный "
                             "противник, не доказательство стойкости) и в контрфакте «единая форма на всех»; рядом — "
                             "сдвиг оценки уровня относительно того же слабого без утечки") if lf else None,
            "recompute": m.get("command"), "code_ref": "backend/app/modules/validation/cheat_bots.py"}


def _bot_gap(m: dict) -> float | None:
    """На сколько логитов «слабый» бот ниже порога — из meta прогона (поле gap или текст bot_theta), не константой."""
    if isinstance(m.get("gap"), (int, float)):
        return float(m["gap"])
    import re as _re
    x = _re.search(r"−\s*([0-9]+(?:[.,][0-9]+)?)\s*логита", str(m.get("bot_theta") or ""))
    return float(x.group(1).replace(",", ".")) if x else None


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
    if a5.get("hh_match"):  # для сайта — блок site (отложенный набор А5), не набор разработки dev
        h = a5["hh_match"]
        site = h.get("site") if isinstance(h.get("site"), dict) else {k: v for k, v in h.items() if k != "dev"}
        return site
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
    # аудит распознавания: новейший (v5, выборка со стратами и разбором расхождений), иначе прежний
    oc = _load(A8_DIR / "ocr_audit_v5.json") or _load(A8_DIR / "ocr_audit.json")
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
    stx = ((gv or {}).get("st") or {}).get("extra") or {}
    hx = ((gv or {}).get("hard") or {}).get("extra") or {}
    if stx.get("confident_accuracy_final") and hx.get("confident_accuracy_final"):
        # итоговый прогон: точность уверенного вердикта — всегда парой с долей уверенных; S-T и жёсткие рядом
        a, sh, fc = stx["confident_accuracy_final"], stx.get("confident_share_final") or {}, stx.get("false_confirm_all") or {}
        ha, hsh, hfc = hx["confident_accuracy_final"], hx.get("confident_share_final") or {}, hx.get("false_confirm_all") or {}
        va = ((gv.get("st") or {}).get("view") or {}).get("verdict_accuracy") or {}
        hva = (gv.get("main") or {}).get("verdict_accuracy") or {}
        cards.append({
            "id": "grade_verdict", "eyebrow": "Точность уверенного вердикта по грейду", "value": pct(a["value"]), "accent": "%",
            "subtext": (f"уверенных — {pct(sh.get('value'))} %; верный вердикт по всем, включая «нужен доп. этап», — "
                        f"{pct(va.get('value'))} %; ложное подтверждение — {pct(fc.get('value'))} % всех кандидатов "
                        f"(стандартные условия). В жёстких: {pct(ha['value'])} %, уверенных {pct(hsh.get('value'))} %, "
                        f"по всем {pct(hva.get('value'))} %, ложных подтверждений {pct(hfc.get('value'))} % · симуляция "
                        f"продукта, модельные кандидаты, не люди"),
            "provenance": f"итоговый прогон симуляции продукта, {(gv['main'] or {}).get('date')}",
            "recompute": gv["recompute"], "code_ref": gv["code_ref"]})
    elif gv and gv["main"].get("verdict_accuracy"):
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
        er = ((fsp.get("ocr_audit") or {}).get("errors") or {}) if isinstance(fsp.get("ocr_audit"), dict) else {}
        if all(isinstance(er.get(k), dict) for k in ("fio", "place", "birth_date")):
            bits.append(f"проверка распознавания: ошибок в ФИО — {er['fio'].get('errors')} из {er['fio'].get('checked')}, "
                        f"в местах — {er['place'].get('errors')} из {er['place'].get('checked')}, в датах рождения — "
                        f"{er['birth_date'].get('errors')} из {er['birth_date'].get('checked')}")
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


def final_blocks() -> tuple[dict, dict, dict]:
    """Итоговые прогоны поправки №2: (жёсткий основной, S-T заголовок, все артефакты по ключам)."""
    arts = {k: _load(p) for k, p in {**PS_FINAL, **PS_ST}.items()}
    arts = {k: v for k, v in arts.items() if v}
    hard = arts.get("hard") or {}
    st = arts.get("st") or {}
    return hard, st, arts


def final_claim(st: dict | None, hard: dict | None) -> str | None:
    """Формулировка для сайта и README по итоговому прогону — только из артефактов, S-T и жёсткие вместе."""
    if not st or not hard or not st.get("extra") or not hard.get("extra"):
        return None

    def one(x: dict) -> str:
        e = x["extra"]
        g = lambda k: (e.get(k) or {}).get("value")
        mt = e.get("minutes_total") or {}
        va = ((x.get("view") or {}).get("verdict_accuracy") or {}).get("value")
        return (f"точность уверенного вердикта {pct(g('confident_accuracy_final'))} % при доле уверенных "
                f"{pct(g('confident_share_final'))} % (верный вердикт по всем, включая «нужен доп. этап», — {pct(va)} %), "
                f"ложное подтверждение {pct(g('false_confirm_all'))} % всех кандидатов, "
                f"точный грейд {pct(g('exact_grade_all'))} % по 6 ступеням ({pct(g('exact_grade_final_4'))} % по 4), "
                f"±1 ступень — {pct(g('within_one_final'))} %; время — в среднем {num(mt.get('mean'), 0)} мин "
                f"(p90 {num(mt.get('p90'), 0)})")
    n_st = ((st.get("view") or {}).get("n"))
    n_h = ((hard.get("view") or {}).get("n"))
    return (f"Симуляция продукта — тот же движок и банк, что на стенде; модельные кандидаты, не люди; один прогон на "
            f"отложенных зёрнах после выбора настроек на обучающих. Стандартные условия (как в аналогичных решениях, "
            f"N = {int_ru(n_st)}): {one(st)}. Жёсткие условия (угадывание, завышенные заявки, осторожные параметры "
            f"заданий, N = {int_ru(n_h)}): {one(hard)}.")


def external_block() -> dict | None:
    """Внешний бенчмарк подбора (А17): открытый набор Djinni, один прогон после FREEZE — как есть из артефакта."""
    d = _load(DJINNI)
    if not d:
        return None
    mc = d.get("main_config") or "B_grade_from_text"
    c = (d.get("configs") or {}).get(mc) or {}
    sm = c.get("summary") or {}
    dr, bm = sm.get("draft") or {}, sm.get("bm25") or {}
    diff = c.get("draft_minus_bm25") or {}
    nd = (dr.get("ndcg@10") or {})
    return {"djinni": {
        "dataset": d.get("dataset"), "condition_ru": d.get("condition"), "date": d.get("date"),
        "main_config": mc, "main_metric": d.get("main_metric"),
        "draft": {k: dr.get(k) for k in ("ndcg@10", "mrr_rel1", "p@5_rel1", "mrr_rel2", "p@5_rel2") if dr.get(k)},
        "bm25": {k: bm.get(k) for k in ("ndcg@10", "mrr_rel1", "p@5_rel1") if bm.get(k)},
        "draft_minus_bm25": diff, "success_rule_ru": d.get("success_rule"), "success": d.get("success"),
        "freeze": d.get("freeze"), "git_head_at_run": d.get("git_head_at_run"), "recompute": d.get("command"),
        "source": str(DJINNI.relative_to(ROOT)),
        "claim_ru": (f"Внешний открытый набор вакансий и анкет (не наши данные, метки-посредники, не люди): nDCG@10 "
                     f"{num(nd.get('mean'), 3)} [{num((nd.get('ci95') or [None])[0], 3)}; "
                     f"{num((nd.get('ci95') or [None, None])[1], 3)}], выше BM25 на "
                     f"{num((diff.get('ndcg@10') or {}).get('diff'), 3)} — один прогон после фиксации протокола")
                    if nd.get("mean") is not None else None}}


def build() -> dict:
    bank, gv, cheat = bank_block(), grade_verdict_block(), cheat_block()
    hard, st, arts = final_blocks()
    if hard or st:
        gv = dict(gv or {})
        gv["hard"] = {"extra": _extra(hard), "view": _ps_view(hard)} if hard else None
        gv["st"] = {"extra": _extra(st), "view": _ps_view(st)} if st else None
        gv["sensitivity"] = {k: {"view": _ps_view(v), "condition_ru": _cond_ru(v)} for k, v in arts.items()
                             if k not in ("hard", "st")}
        cl = final_claim(gv.get("st"), gv.get("hard"))
        if cl:
            gv["claim_ru"] = cl
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
        "external_benchmarks": external_block(),
        "hh_match": hh,
        "anticheat": anticheat,
        "fsp_protocols": fsp,
        "mutation_testing": mutation,
        "load": load,
        "demo": demo_block(),
        "landing_cards": cards,
        "top5": top5_from(st),
        "top5_hard": top5_from(hard),
        "top5_meta": top5_meta(hard, st),
        "jury_banner": {"headline_ru": headline, "claims_ru": claims},
        "recompute_table": recompute_table(bank, gv, cheat, matching, hh, anticheat, fsp, load),
    }


REPORT_MD = ROOT / "docs" / "validation" / "VALIDATION_REPORT.md"


WITH_RU = {"confident_share": "доля уверенных вердиктов", "among_overclaim": "среди завысивших заявку",
           "grades_5": "по 5 ступеням (Lead и Principal вместе)", "grades_4": "по 4 ступеням (ещё Стажёр и Junior вместе)",
           "not_underclaim": "среди тех, кому продукт определяет грейд (без занизивших)",
           "main_part": "основная часть (одна сессия), 6 ступеней", "main_part_grades_5": "основная часть, 5 ступеней",
           "main_part_grades_4": "основная часть, 4 ступени", "above_true": "грейд выше истинного",
           "gross_error_2plus": "ошибка на 2+ ступени", "exact_agreement": "тот же грейд при повторе",
           "decision_agreement": "то же решение (подтверждён / нет) при повторе",
           "kappa_cohen_unweighted": "согласие грейда при повторе (κ Коэна без весов)", "kappa_w_with_truth": "κw с истиной",
           "kappa_decision": "κ Коэна решения «подтверждён / нет» при повторе",
           "kappa_w_with_truth_4": "κw с истиной по 4 ступеням",
           "far_grades4": "4 ступени, кандидаты дальше 0,25 от любого порога",
           "above_true_5": "грейд выше истинного (по 5 ступеням)"}


def _f(x: dict | None, d: int = 1) -> str:
    """«78,4 % [77,0; 79,8], k / n» из frac-словаря."""
    if not isinstance(x, dict) or x.get("value") is None:
        return "—"
    c = x.get("ci95") or [None, None]
    kn = f", {x.get('k')} / {x.get('n')}" if x.get("k") is not None else ""
    return f"{pct(x['value'], d)} % [{pct(c[0], d)}; {pct(c[1], d)}]{kn}"


def _kap(x: dict | None) -> str:
    if not isinstance(x, dict) or x.get("value") is None:
        return "—"
    c = x.get("ci95") or [None, None]
    return f"{num(x['value'], 3)} [{num(c[0], 3)}; {num(c[1], 3)}]"


def final_md(n: dict) -> list[str]:
    """Раздел итоговых прогонов (поправки №2–3): S-T и жёсткие условия рядом, чувствительность, боты, внешний набор."""
    gv = n.get("grade_verdict") or {}
    L: list[str] = []
    rows = [("st", "Стандартные условия (S-T, как в аналогичных решениях)"), ("hard", "Жёсткие условия (основной протокол)")]
    if not any((gv.get(k) or {}).get("extra") for k, _ in rows):
        return L
    L += ["## Итоговый прогон симуляции продукта (один прогон на отложенных зёрнах)", "",
          "Модельные кандидаты, не люди. Движок, банк и настройки — те же, что на стенде; «истина» — отдельный поток "
          "случайных чисел; настройки выбраны только на обучающих зёрнах (протокол `docs/validation/PRODUCT_SIM_PROTOCOL.md`, "
          "поправки №2–3).", ""]
    for key, title in rows:
        e = (gv.get(key) or {}).get("extra")
        if not e:
            continue
        top = n.get("top5" if key == "st" else "top5_hard") or []
        L += [f"### {title}", "", e.get("condition_ru") or "", "", "| Метрика | Значение [95 % ДИ], k / n |", "|---|---|"]
        for it in top:
            v = (f"{num(it['value'], 3)} [{num((it.get('ci95') or [None])[0], 3)}; {num((it.get('ci95') or [None, None])[1], 3)}]"
                 if it["id"] == "retest_kappa_w" else _f(it))
            L.append(f"| {it['label_ru']} | {v} |")
            for k2, v2 in (it.get("with") or {}).items():
                L.append(f"| — {WITH_RU.get(k2, k2)} | {_kap(v2) if 'kappa' in k2 else _f(v2)} |")
        far = e.get("far_from_cut_0_25") or {}
        fx = e.get("fixed_vs_adaptive") or {}
        L += [f"| Точный грейд вдали от порога (> 0,25), N = {far.get('n')} | {_f(far.get('exact_grade_final'))} |",
              f"| κw с истиной (весь путь) | {_kap(e.get('kappa_w_with_truth_final'))} |",
              f"| Ложный отказ (от всех) | {_f(e.get('false_reject_all'))} |",
              f"| Без решения после всего пути | {_f(e.get('undecided_final'))} |",
              f"| Второй этап / устная защита | {_f(e.get('followup_share'))} / {_f(e.get('oral_share'))} |",
              f"| Минуты: основная часть — среднее (p90) | {num((e.get('minutes_main') or {}).get('mean'), 1)} "
              f"({num((e.get('minutes_main') or {}).get('p90'), 1)}) |",
              f"| Минуты: весь путь — среднее (p90) | {num((e.get('minutes_total') or {}).get('mean'), 1)} "
              f"({num((e.get('minutes_total') or {}).get('p90'), 1)}) |"]
        if fx:
            a, f = fx.get("adaptive_main") or {}, fx.get("fixed") or {}
            L += [f"| Адаптивный / фиксированная форма той же длины — точный грейд, N = {fx.get('n')} | "
                  f"{_f(a.get('exact_grade'))} / {_f(f.get('exact_grade'))} |",
                  f"| — по 4 ступеням | {_f(a.get('exact_grade_4'))} / {_f(f.get('exact_grade_4'))} |"]
        oc = e.get("oc_curve") or []
        if isinstance(oc, list) and oc:
            L += ["", "Кривая OC — доля «подтверждён» (весь путь) по θ − порог заявки: " + "; ".join(
                f"[{num(b.get('from'), 2)}; {num(b.get('to'), 2)}) — {pct(b.get('p_confirmed_final'))} % (N = {b.get('n')})"
                for b in oc if b.get("n")) + "."]
        L += ["", f"Пересчёт: `{e.get('recompute')}`.", ""]
    sens = gv.get("sensitivity") or {}
    if sens:
        L += ["### Проверка на прочность (те же настройки, другие допущения о мире)", "",
              "| Мир | Условие | Точный грейд (6 / 5 ступеней) | ±1 | Ложное подтв. (от всех) | Точность уверенного |",
              "|---|---|---|---|---|---|"]
        for k, v in sens.items():
            w = v.get("view") or {}
            L.append(f"| {k} | {v.get('condition_ru')} | {_f(w.get('exact_grade'))} / {_f(w.get('exact_grade_5'))} | "
                     f"{_f(w.get('within_one'))} | {_f(w.get('false_confirm_all'))} | {_f(w.get('confident_accuracy_final'))} |")
        L.append("")
    ext = (n.get("external_benchmarks") or {}).get("djinni")
    if ext:
        L += ["### Подбор на внешнем открытом наборе (агент А17)", "", ext.get("claim_ru") or "", "",
              f"Условие: {ext.get('condition_ru')}. Пересчёт: `{ext.get('recompute')}`.", ""]
    return L


def report_md(n: dict) -> str:
    """docs/validation/VALIDATION_REPORT.md — только из NUMBERS.json (генерируется вместе с ним)."""
    L = ["# Отчёт валидации «Драфт» (генерируется tools/publish/gen_numbers.py из docs/NUMBERS.json)", "",
         f"Коммит {n['git_commit']}, {n['generated_at']}. Чисел, введённых руками, здесь нет.", ""]
    L += final_md(n)
    gv = n.get("grade_verdict")
    if gv and gv.get("main"):
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
        if sel.get("rows") and "L" in (sel["rows"][0] or {}):  # поправка №3: выбор скриптом train_choice.py
            L += ["", f"Выбор настроек на обучающих зёрнах: {sel.get('rule_ru')} Выбрано {sel.get('chosen')} — "
                      f"{sel.get('reason_ru')}. Испробовано конфигураций: {len(sel['rows'])}.", "",
                  "| Конфигурация | L = 3·FC + FR | Ложное подтв. | Ложный отказ | Точный грейд | Тот же грейд при повторе | "
                  "Минуты всего (p90) | Ограничения |", "|---|---|---|---|---|---|---|---|"]
            for r in sel["rows"]:
                env = ", ".join(f"{k.replace('ASSESSMENT_', '')}={v}" for k, v in (r.get("env") or {}).items())
                L.append(f"| {r['config']} ({env}) | {num(r.get('L'), 4)} | {pct(r.get('FC'))} % | {pct(r.get('FR'))} % | "
                         f"{pct(r.get('exact_grade_final'))} % | {pct(r.get('retest_exact'))} % | "
                         f"{num(r.get('minutes_total_mean'), 1)} ({num(r.get('minutes_total_p90'), 1)}) | "
                         f"{'да' if r.get('passes') else '; '.join(r.get('fails') or [])} |")
        elif sel.get("rows"):
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
