#!/usr/bin/env python3
"""Единый набор чисел проекта: docs/NUMBERS.json и блоки в README.md, docs/testing.md, docs/LOAD_TEST.md.

    python tools/publish/gen_numbers.py                       # пересчитать числа из дерева и обновить блоки
    python tools/publish/gen_numbers.py --tests-log LOG       # + взять число тестов и покрытие из журнала pytest (heavy-pytest)
    python tools/publish/gen_numbers.py --check               # код выхода 1, если блоки расходятся с деревом (для CI)

Откуда числа (всё считается из файлов репозитория, без сети):
  * банк заданий — backend/assessment_bank/BANK_SYNC.json (семейства, направления, итог валидатора);
  * миграции — backend/migrations/versions (число ревизий, единственная голова);
  * лимиты памяти — mem_limit в docker-compose.yml;
  * подбор — docs/validation/matching_bench.json (`make bench`, скрытая истина, синтетика — модель, не люди);
  * сквозные сценарии — e2e/tests/*.spec.ts (число файлов и вызовов test(...) в коде);
  * автотесты бэкенда и покрытие — только из журнала прогона (--tests-log): строка «N passed, M skipped in T» и
    итог покрытия; без журнала остаются прежние значения из docs/NUMBERS.json вместе с SHA и датой прогона.
Блоки в файлах ограничены строками `<!-- numbers:begin -->` … `<!-- numbers:end -->` (и `limits`); остальной текст не трогается.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NUMBERS = ROOT / "docs" / "NUMBERS.json"
TARGETS = {  # файл → имя блока
    "README.md": "numbers",
    "docs/testing.md": "numbers",
    "docs/LOAD_TEST.md": "limits",
}


def fnum(x: float, nd: int = 3) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def static_numbers() -> dict:
    bank = json.loads((ROOT / "backend/assessment_bank/BANK_SYNC.json").read_text(encoding="utf-8"))
    summ = bank["validation"]["summary"]
    # миграции: ревизии и единственная голова
    revs, downs = {}, set()
    for p in sorted((ROOT / "backend/migrations/versions").glob("*.py")):
        s = p.read_text(encoding="utf-8")
        m = re.search(r"^revision(?:\s*:\s*str)?\s*=\s*['\"]([^'\"]+)['\"]", s, re.M)
        if not m:
            continue
        revs[m.group(1)] = p.name
        d = re.search(r"^down_revision[^=]*=\s*(.+)$", s, re.M)
        if d:
            downs.update(re.findall(r"['\"]([^'\"]+)['\"]", d.group(1)))
    heads = sorted(set(revs) - downs)
    # лимиты памяти
    limits: dict[str, int] = {}
    cur = None
    for line in (ROOT / "docker-compose.yml").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^  ([a-z0-9_-]+):\s*$", line)
        if m:
            cur = m.group(1)
        m = re.match(r"^\s+mem_limit:\s*(?:\$\{[A-Z_]+:-)?(\d+)([mg])", line)
        if m and cur:
            limits[cur] = int(m.group(1)) * (1024 if m.group(2) == "g" else 1)
    # подбор
    bench = json.loads((ROOT / "docs/validation/matching_bench.json").read_text(encoding="utf-8"))
    plat = bench["metrics"]["platform"]
    sig = bench["signature"]
    # отчёт /validation (make validate): на каком банке посчитан
    rep = json.loads((ROOT / "backend/app/modules/validation/data/report.json").read_text(encoding="utf-8"))
    exp = json.loads((ROOT / "backend/app/modules/assessment/exposure_k.json").read_text(encoding="utf-8"))
    validation = {
        "report_generated_at": rep.get("generated_at", "?")[:10], "report_bank_families": rep.get("bank", {}).get("n_families"),
        "exposure_generated_at": exp.get("generated_at", "?")[:10], "exposure_bank_families": exp.get("bank", {}).get("n_families"),
        "report_matches_bank": rep.get("bank", {}).get("content_hash") == bank["content_hash"],
    }
    # точность уровня (Я22): весь путь при действующем пороге (make path-retest) и перебор правил (make grade-sweep)
    grade = None
    pr_p = ROOT / "backend/app/modules/validation/data/path_retest.json"
    gs_p = ROOT / "backend/app/modules/validation/data/grade_sweep.json"
    if pr_p.exists() and gs_p.exists():
        pr = json.loads(pr_p.read_text(encoding="utf-8"))
        gs = json.loads(gs_p.read_text(encoding="utf-8"))
        pts = {q["key"]: q["metrics"] for q in gs["points"]}
        base, ch = pts.get(gs["baseline_key"], {}), pts.get((gs.get("choice") or {}).get("key"), {})
        r3 = lambda x: round(x, 3) if isinstance(x, (int, float)) else x  # noqa: E731
        grade = {
            "confirm_level": pr["config"].get("confirm_level"), "path_retest_commit": pr["signature"]["commit"],
            "path_retest_at": pr["signature"]["generated_at"][:10], "sweep_commit": gs["signature"]["commit"],
            "sweep_points": len(gs["points"]),
            "before": {k: r3(base.get(k)) for k in ("exact", "over", "under", "none", "retest_exact", "retest_kappa", "minutes_mean")},
            "now": {k: r3(ch.get(k)) for k in ("exact", "over", "under", "none", "retest_exact", "retest_kappa", "minutes_mean")},
            # Д5: тот же порог в контрольном прогоне всего пути с настройками продукта (make path-retest) — эти числа
            # показывает первый экран /validation (/api/validation/headline); перебор правил — на своём снимке банка
            "sweep_bank": gs["signature"].get("bank"), "path_retest_bank": pr["signature"].get("bank"),
            "path_retest_bank_families": pr["config"].get("n_families"),
            "path_retest": {k: r3(v) for k, v in (
                ("exact", pr["total"]["truth"]["exact"]), ("over", pr["total"]["truth"]["over_share"]),
                ("under", pr["total"]["truth"]["under_share"]), ("none", pr["total"]["truth"]["no_category_share"]),
                ("retest_exact", pr["total"]["path_grade"]["exact"]), ("retest_kappa", pr["total"]["path_grade"]["kappa_w"]))},
        }
    # W1: три прозрачных числа точности грейда (make accuracy-views) — первыми в grade_accuracy
    av_p = ROOT / "backend/app/modules/validation/data/accuracy_views.json"
    if grade is not None and av_p.exists():
        av = json.loads(av_p.read_text(encoding="utf-8"))
        v = av["views"]
        rt = v["strict_pool"].get("retest") or {}
        grade = {"views": {
            "far_from_cut": {"exact": v["far_from_cut"]["exact"], "ci": v["far_from_cut"]["exact_ci"],
                             "share": v["far_from_cut"]["share"], "rule": "одна сессия, |θ − порог| ≥ 0,45"},
            "no_under_claim": {"exact": v["no_under_claim"]["exact"], "ci": v["no_under_claim"]["exact_ci"],
                               "share": v["no_under_claim"]["share"], "over": v["no_under_claim"]["over"],
                               "rule": "заявленный ≥ истинного, двухэтапное подтверждение у границы"},
            "strict_pool": {"exact": v["strict_pool"]["exact"], "ci": v["strict_pool"]["exact_ci"],
                            "under_claim_share": v["strict_pool"]["under_claim_share"],
                            "retest_exact": rt.get("exact"), "retest_kappa": rt.get("kappa_w"),
                            "within_1": rt.get("within_1"), "rule": "весь пул, одна сессия"},
            "commit": av["signature"]["commit"], "bank": av["signature"].get("bank"),
            "generated_at": av["signature"]["generated_at"][:10], "command": "make accuracy-views"}, **grade}
    # W1: Lead/Principal — основной сценарий второго этапа (make grades-ext-need)
    gx_p = ROOT / "backend/app/modules/validation/data/grades_ext_need.json"
    lead = None
    if gx_p.exists():
        gx = json.loads(gx_p.read_text(encoding="utf-8"))
        cur = gx.get("main") or {}
        vv = (gx.get("variants") or {}).get(cur.get("key") or "")
        if vv:
            b_ = vv["by_true_level"]
            lead = {"scenario": cur["key"], "text": vv.get("text"), "lead": (b_.get("lead") or {}).get("exact"),
                    "principal": (b_.get("principal") or {}).get("exact"), "senior": (b_.get("senior") or {}).get("exact"),
                    "above": vv.get("above"), "above_ext": vv.get("above_ext"), "minutes_mean": vv.get("minutes_mean"),
                    "previous": cur.get("previous"), "command": "make grades-ext-need"}
    # W1: подбор на вакансиях hh.ru (модельный пул, модель, не люди)
    hh_p = ROOT / "backend/app/modules/validation/data/hh_match.json"
    hh = None
    if hh_p.exists():
        h = json.loads(hh_p.read_text(encoding="utf-8"))
        hh = {k: h.get(k) for k in ("generated_at", "code_commit", "algorithm", "n", "catalog_directions", "overall",
                                    "catalog_only") if h.get(k) is not None}
        hh["note"] = "модельный пул кандидатов демо-стенда (модель, не люди); покрытие зависит от состава пула"
    # e2e в коде
    specs = sorted((ROOT / "e2e/tests").glob("*.spec.ts"))
    n_tests = sum(len(re.findall(r"^\s*test\(", p.read_text(encoding="utf-8"), re.M)) for p in specs)
    return {
        "bank": {
            "families": bank["n_families"], "by_direction": bank["by_direction"] if all(isinstance(v, int) for v in bank["by_direction"].values())
            else {k: v["families"] for k, v in bank["by_direction"].items()},
            "source_commit": bank["commit"], "content_hash": bank["content_hash"],
            "pass": summ["status"].get("PASS", 0), "warn": summ["status"].get("WARN", 0), "fail": summ.get("n_fail", 0),
            "checks": summ["n_checks"], "checks_failed": summ["n_checks_failed"], "variants": summ["n_variants_generated"],
            "unique_variants": summ["n_unique_variants"],
        },
        "migrations": {"revisions": len(revs), "heads": heads},
        "memory_limits_mib": limits,
        "matching": {
            "algorithm": bench["algorithm"], "world": sig["world"], "seed": sig["seed"], "bench_commit": sig["commit"],
            "bank_hash": sig["bank"], "generated_at": sig["generated_at"],
            "p5": plat["p@5"], "ndcg10": plat["ndcg@10"], "mrr": plat["mrr"], "p10": plat["p@10"],
            "protocol": "строгий (основной)",
            # W1: стандартный сбалансированный протокол (≥ 10 релевантных в категории потребности), тот же подбор
            "balanced": ({"p5": bp["p@5"], "p10": bp["p@10"], "ndcg10": bp["ndcg@10"], "mrr": bp["mrr"],
                          "config_hash": bench["balanced"]["config_hash"],
                          "relevant_in_category": bench["balanced"]["world"]["relevant_in_category"]}
                         if (bp := ((bench.get("balanced") or {}).get("metrics") or {}).get("platform")) else None),
        },
        "lead_principal": lead,
        "hh_match": hh,
        "e2e_in_code": {"spec_files": len(specs), "scenarios": n_tests},
        "validation_report": validation,
        "grade_accuracy": grade,
    }


def _num(text: str, pattern: str, default: float | int | None = None, flags: int = re.M):
    """Первое число по шаблону (запятая как десятичный разделитель, пробелы в разрядах), иначе default."""
    m = re.search(pattern, text, flags)
    if not m:
        return default
    raw = m.group(1).replace("\u00a0", "").replace(" ", "").replace(",", ".")
    return int(raw) if re.fullmatch(r"-?\d+", raw) else float(raw)


def measured_numbers() -> dict:
    """Числа для сопроводительной документации, у которых нет отдельного машинного источника в репозитории:
    читаются из документов-замеров (docs/LOAD.md, docs/BOOT.md), из файлов расчёта (evidence_bench.json) и из
    констант демо-данных (app/modules/demo/seed.py, integrations/vacancies/demo.py). Доступность (a11y) приходит
    из axe.json прогона (`--axe-json`), иначе остаётся прежней из docs/NUMBERS.json (как тесты)."""
    load = (ROOT / "docs/LOAD.md").read_text(encoding="utf-8")
    boot = (ROOT / "docs/BOOT.md").read_text(encoding="utf-8")
    ev = json.loads((ROOT / "backend/app/modules/validation/data/evidence_bench.json").read_text(encoding="utf-8"))
    seed = (ROOT / "backend/app/modules/demo/seed.py").read_text(encoding="utf-8")
    vac = (ROOT / "backend/app/integrations/vacancies/demo.py").read_text(encoding="utf-8")

    def _entries(src: str, name: str) -> int:  # число элементов списка кортежей/словарей NEEDS = [...] в исходнике
        m = re.search(rf"^{name} = \[(.*?)^\]", src, re.S | re.M)
        body = m.group(1) if m else ""
        return len(re.findall(r"^\s{4}\(|^\s{4}\{|^\s{4}dict\(", body, re.M))

    return {
        # docs/LOAD.md: «Развёртывание с нуля по README | **291 с …»
        "deploy": {"fresh_seconds": _num(load, r"Развёртывание с нуля по README \| \*\*(\d+) с")},
        # docs/BOOT.md: «| стартовый JS на проводе, gzip | 418 295 (…) | 101 458 (…) |» — в КБ (÷1000, как в тексте документа)
        "boot": {"js_kb_before": round((_num(boot, r"стартовый JS на проводе, gzip \| ([\d  ]+) \(") or 0) / 1000),
                 "js_kb_after": round((_num(boot, r"стартовый JS на проводе, gzip \| [\d  ]+ \([^|]*\| ([\d  ]+) \(") or 0) / 1000)},
        # docs/LOAD.md: 100 пользователей — «42 ошибки (0,51 %)»; исправление пула и отчёта — «1,3 → 24,1 запроса/с, 7 × 500 → 0 ошибок»
        "load": {"u100_error_share": round((_num(load, r"\*\*\d+ ошибк[аи] \(([\d,]+) %\)") or 0) / 100, 4),
                 "fix_rps_before": _num(load, r"\*\*([\d,]+) → [\d,]+ запрос"),
                 "fix_rps_after": _num(load, r"\*\*[\d,]+ → ([\d,]+) запрос"),
                 "fix_errors_after": _num(load, r"\d+ × 500 → (\d+) ошибок")},
        # демо-данные платформы (python -m app.modules.demo.seed): кандидаты и работодатели — из docstring модуля, потребности и
        # вакансии — по спискам NEEDS + INTERN_NEEDS и VACANCIES
        "demo": {"candidates": _num(seed, r"Демо-данные: (\d+) кандидатов"), "employers": _num(seed, r"(\d+) работодателей"),
                 "needs": _entries(seed, "NEEDS") + _entries(seed, "INTERN_NEEDS"), "vacancies": _entries(vac, "VACANCIES")},
        # evidence_bench.json: стоимость ответа при включённом GRADING_EVIDENCE (полный прогон 406, оценка + скептик)
        "evidence": {"cost_usd_per_answer": ev["full"]["cost_per_answer_on"], "n": ev["full"]["n"]},
    }


def parse_axe(path: Path) -> dict:
    """Итог axe-аудита (tools/a11y/axe_audit.cjs → axe.json): проходов экран × ширина, нарушений по степеням, экранов с
    горизонтальной прокруткой."""
    d = json.loads(path.read_text(encoding="utf-8"))
    rows = [r for r in d["results"] if not r.get("error")]
    out = {"screens": len({r["screen"] for r in rows}), "passes": len(rows), "errors": len(d["results"]) - len(rows),
           "critical": 0, "serious": 0, "moderate": 0, "minor": 0, "hscroll": 0}
    for r in rows:
        for k in ("critical", "serious", "moderate", "minor"):
            out[k] += int((r.get("counts") or {}).get(k, 0) or 0)
        if (r.get("hscroll") or 0) > 0:
            out["hscroll"] += 1
    return out


def parse_log(path: Path) -> dict:
    t = path.read_text(encoding="utf-8", errors="replace")
    out: dict = {}
    m = None
    for m in re.finditer(r"^(?:=+ )?(?:(\d+) failed, )?(\d+) passed(?:, (\d+) skipped)?[^\n]*? in ([\d.]+)s", t, re.M):
        pass
    if not m:
        raise SystemExit(f"в журнале {path} нет итоговой строки pytest «N passed … in T s»")
    out["failed"] = int(m.group(1) or 0)
    out["passed"] = int(m.group(2))
    out["skipped"] = int(m.group(3) or 0)
    out["seconds"] = float(m.group(4))
    cov = re.findall(r"Total coverage: (\d+(?:\.\d+)?)%", t) or re.findall(r"^TOTAL\s+\d+\s+\d+\s+(\d+(?:\.\d+)?)%", t, re.M)
    if cov:
        out["coverage_pct"] = round(float(cov[-1]), 1)
    ex = re.findall(r"^EXIT=(\d+)", t, re.M)
    out["exit"] = int(ex[-1]) if ex else None
    return out


def git_short() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "?"


def validation_row(v: dict, families: int) -> str:
    def dm(x: str) -> str:
        return ".".join(reversed(x.split("-")[1:])) if x != "?" else "?"
    d = dm(v["report_generated_at"])
    if v["report_matches_bank"]:
        tail = "соответствует текущему банку"
    else:
        tail = (f"**на банке из {v['report_bank_families']} семейств, а в банке сейчас {families}: пересчёт `make validate` (≈ 21 мин в один процесс: K ≈ 4 мин, симуляция ≈ 17 мин) "
                f"даст другие числа симуляции, повтора и утечки**")
    return (f"| Отчёт страницы `/validation` (симуляция теста, повтор, утечка) | посчитан {d}; {tail}; константы показа `exposure_k.json` — "
            f"{dm(v['exposure_generated_at'])} на {v['exposure_bank_families']} семействах | `make validate`, `backend/app/modules/validation/data/report.json` |")


def grade_row(g: dict | None) -> list[str]:
    if not g:
        return []
    b, c = g["before"], g["now"]
    pc = lambda x: fnum(100 * x, 1) + " %"  # noqa: E731
    return [f"| Точность уровня (модель, не люди) | порог уверенности P ≥ {fnum(g['confirm_level'], 1)}: точно истинный уровень "
            f"**{pc(c['exact'])}** (было {pc(b['exact'])} при P ≥ 0,8), выше {pc(c['over'])}, ниже {pc(c['under'])}, без категории "
            f"{pc(c['none'])}; повтор: совпало {pc(c['retest_exact'])}, κw {fnum(c['retest_kappa'])}; ≈ {fnum(c['minutes_mean'], 0)} мин (перебор правил `make grade-sweep`)"
            + (f"; тот же порог в контрольном прогоне всего пути с настройками продукта (первый экран `/validation`, пул 5 направлений — "
               f"{g.get('path_retest_bank_families') or '—'} семейств): точно {pc(p['exact'])}, выше {pc(p['over'])}, повтор "
               f"{pc(p['retest_exact'])}, κw {fnum(p['retest_kappa'])}"
               + ("" if g.get("sweep_bank") == g.get("path_retest_bank") else " — перебор посчитан на другом снимке банка")
               if (p := g.get("path_retest")) else "")
            + f" | перебор {g['sweep_points']} вариантов, коммит `{g['sweep_commit']}`, банк `{g.get('sweep_bank') or '—'}`; путь — "
            f"коммит `{g['path_retest_commit']}`, банк `{g.get('path_retest_bank') or '—'}`, {g['path_retest_at']}; `make grade-sweep`, "
            "`make path-retest`, `docs/validation/GRADE_ACCURACY.md` |"] + ([
        f"| Точность грейда: три числа (модель, не люди) | а) вдали от порога (\\|θ − порог\\| ≥ 0,45, {pc(av['far_from_cut']['share'])} пула): "
        f"**{pc(av['far_from_cut']['exact'])}**; б) без занижения заявки ({pc(av['no_under_claim']['share'])} пула, два этапа у "
        f"границы): **{pc(av['no_under_claim']['exact'])}**, выше {pc(av['no_under_claim']['over'])}; в) строго, весь пул (заявили ниже "
        f"истинного {pc(av['strict_pool']['under_claim_share'])}): **{pc(av['strict_pool']['exact'])}**, повтор "
        f"{pc(av['strict_pool']['retest_exact'])}, κw {fnum(av['strict_pool']['retest_kappa'])}, ±1 {pc(av['strict_pool']['within_1'])} | "
        f"коммит `{av['commit']}`, банк `{av.get('bank') or '—'}`, {av['generated_at']}; `make accuracy-views`, "
        "`docs/validation/ACCURACY_VIEWS.md` |"] if (av := g.get("views")) else [])


def render_numbers(n: dict) -> str:
    b, mg, ml, mt, e2 = n["bank"], n["migrations"], n["memory_limits_mib"], n["matching"], n["e2e_in_code"]
    t = n.get("tests", {})
    dirs = ", ".join(f"{k} {v}" for k, v in b["by_direction"].items())
    lim = ", ".join(f"{k} {v} МиБ" for k, v in ml.items() if k != "llm-local")
    if "llm-local" in ml:
        lim += f"; профиль llm-local — {ml['llm-local'] // 1024} ГиБ"
    cov = f"; покрытие строк {fnum(t['coverage_pct'], 1)} % при пороге 80 %" if t.get("coverage_pct") else ""
    rows = [
        "| Что | Число | Откуда |",
        "|---|---|---|",
        f"| Автотесты бэкенда (`pytest`, SQLite) | **{t.get('passed', '—')} прошли**, пропущено {t.get('skipped', '—')}, упавших {t.get('failed', '—')}{cov} | "
        f"полный прогон на сервере проверок, SHA `{t.get('sha', '—')}`, {t.get('date', '—')}; `make test`, `make coverage` |",
        f"| Банк заданий | **{b['families']} семейств** ({dirs}); валидатор (20 вариантов на семейство): PASS {b['pass']}, WARN {b['warn']}, FAIL {b['fail']} (WARN — открытый ответ без ключа или ключ не исполняется в окружении без Django/JDK; в окружении только с `requirements.txt` WARN больше); "
        f"{b['checks']} проверок ключей исполнением кода, ошибок {b['checks_failed']}; {b['variants']} вариантов, уникальных {b['unique_variants']} | "
        f"`backend/assessment_bank/BANK_SYNC.json`, `make test-bank` |",
        f"| Миграции Alembic | **ревизий: {mg['revisions']}, одна голова `{mg['heads'][0] if len(mg['heads']) == 1 else '/'.join(mg['heads'])}`** | "
        f"`backend/migrations/versions`, `alembic heads` |",
        f"| Подбор (модель, не люди) | P@5 **{fnum(mt['p5']['mean'])}** [{fnum(mt['p5']['lo'])}; {fnum(mt['p5']['hi'])}], "
        f"nDCG@10 **{fnum(mt['ndcg10']['mean'])}** [{fnum(mt['ndcg10']['lo'])}; {fnum(mt['ndcg10']['hi'])}], MRR {fnum(mt['mrr']['mean'])}; "
        f"синтетический мир со скрытой истиной, {mt['world'].split(': ')[-1]}, seed {mt['seed']}, алгоритм `{mt['algorithm']}`"
        + (f"; сбалансированный протокол (≥ 10 релевантных в категории): P@5 {fnum(bl['p5']['mean'])}, P@10 {fnum(bl['p10']['mean'])}, "
           f"nDCG@10 {fnum(bl['ndcg10']['mean'])}, MRR {fnum(bl['mrr']['mean'])}" if (bl := mt.get("balanced")) else "") + " | "
        f"`make bench`, `docs/validation/MATCHING_BENCH.md`, `docs/validation/matching_bench.json` |",
        validation_row(n["validation_report"], b["families"]),
        *grade_row(n.get("grade_accuracy")),
        f"| Сквозные сценарии (Playwright) | {e2['scenarios']} сценариев в {e2['spec_files']} файлах (число в коде, не результат прогона) | `e2e/tests`, `make e2e` |",
        f"| Лимиты памяти контейнеров | {lim} | `docker-compose.yml`, разбор — `docs/LOAD_TEST.md` |",
    ]
    return "\n".join(rows)


def render_limits(n: dict) -> str:
    ml = n["memory_limits_mib"]
    names = {"api": "api (FastAPI)", "db": "db (PostgreSQL 16)", "web": "web (nginx)", "keycloak": "keycloak (ФСП ID, демо, профиль `fsp-id`)"}
    rows = ["| Контейнер | Лимит сейчас, МиБ |", "|---|---:|"]
    for k in ("api", "db", "web", "keycloak"):
        if k in ml:
            rows.append(f"| {names[k]} | {ml[k]} |")
    base = sum(v for k, v in ml.items() if k in ("api", "db", "web"))
    rows.append(f"| **Весь стек без `fsp-id`** | **{base}** |")
    if "keycloak" in ml:
        rows.append(f"| **Весь стек с `fsp-id`** | **{base + ml['keycloak']}** |")
    return "\n".join(rows)


def replace_block(text: str, name: str, body: str) -> tuple[str, bool]:
    pat = re.compile(rf"(<!-- {name}:begin[^>]*-->)(.*?)(<!-- {name}:end -->)", re.S)
    if not pat.search(text):
        return text, False
    return pat.sub(lambda m: m.group(1) + "\n" + body + "\n" + m.group(3), text, count=1), True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests-log")
    ap.add_argument("--sha", help="SHA кода, на котором снят журнал (по умолчанию — текущий HEAD)")
    ap.add_argument("--date", help="дата прогона ДД.ММ.ГГГГ")
    ap.add_argument("--axe-json", help="axe.json прогона tools/a11y/axe_audit.cjs → раздел a11y")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    old = json.loads(NUMBERS.read_text(encoding="utf-8")) if NUMBERS.exists() else {}
    n = static_numbers()
    n.update(measured_numbers())
    n["a11y"] = old.get("a11y", {})
    if a.axe_json:
        n["a11y"] = {**parse_axe(Path(a.axe_json)), "date": a.date or __import__("datetime").date.today().strftime("%d.%m.%Y")}
    n["tests"] = old.get("tests", {})
    if a.tests_log:
        n["tests"] = {**parse_log(Path(a.tests_log)), "sha": a.sha or git_short(), "date": a.date or __import__("datetime").date.today().strftime("%d.%m.%Y")}
    n["note"] = ("Числа посчитаны tools/publish/gen_numbers.py; тесты и покрытие — из журнала прогона. "
                 "Подбор — синтетический мир со скрытой истиной (модель, не люди).")

    bad: list[str] = []
    new_json = json.dumps(n, ensure_ascii=False, indent=1) + "\n"
    if a.check:
        # сравниваем статическую часть (без тестов: они приходят из журнала) и тексты блоков
        for k in ("bank", "migrations", "memory_limits_mib", "matching", "e2e_in_code", "validation_report",
                  "grade_accuracy", "lead_principal", "hh_match", "deploy", "boot", "load", "demo", "evidence"):
            if old.get(k) != n[k]:
                bad.append(f"docs/NUMBERS.json: раздел «{k}» устарел")
    else:
        NUMBERS.write_text(new_json, encoding="utf-8")
    for rel, name in TARGETS.items():
        p = ROOT / rel
        text = p.read_text(encoding="utf-8")
        body = render_numbers(n) if name == "numbers" else render_limits(n)
        new, found = replace_block(text, name, body)
        if not found:
            bad.append(f"{rel}: нет блока <!-- {name}:begin --> … <!-- {name}:end -->")
        elif a.check and new != text:
            bad.append(f"{rel}: блок «{name}» расходится с числами (python tools/publish/gen_numbers.py)")
        elif not a.check:
            p.write_text(new, encoding="utf-8")
    if bad:
        print("\n".join(bad), file=sys.stderr)
        return 1
    print("числа согласованы" if a.check else f"обновлено: docs/NUMBERS.json и блоки в {', '.join(TARGETS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
