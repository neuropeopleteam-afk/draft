"""Валидатор банка заданий.

Для каждого семейства на N seed (по умолчанию 200) проверяем:

1. схему — каждый вариант проходит Pydantic-модель и правила формата;
2. детерминизм — повторная генерация в том же процессе и в отдельном процессе с другим
   PYTHONHASHSEED даёт тот же канонический хэш;
3. ключ ответа — исполнением НАШЕГО кода в песочнице (sandbox.py): вывод совпадает с ключом,
   код с дефектом падает на тестах, а исправление проходит, ровно один вариант исправления
   верен и т. д.; показанный кандидату код входит в исполняемую программу дословно;
4. уникальность — доля различных (по видимому содержанию) вариантов;
5. поверхностное разнообразие — среднее попарное расстояние Жаккара по словам, число
   предметных контекстов, равномерность позиции правильного ответа, разнообразие ключей;
6. инварианты — размер кода, число операций, тип дефекта, число вариантов ответа.
"""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from scipy import stats

from . import registry
from .gen_utils import changed_lines
from .metrics import count_code_lines, count_operations, normalize_output
from .sandbox import RunResult, run_checks
from .schema import Check, FamilySpec, Variant

UNIQUE_FAIL = 0.90
OPEN_MIN_DISTINCT = 40
UNIQUE_WARN = 0.98
JACCARD_WARN = 0.12
CONTEXT_SHARE_WARN = 0.6


@dataclass
class FamilyReport:
    family_id: str
    title: str
    direction: str
    format: str
    target_grades: list[str]
    canary: bool
    n_seeds: int
    status: str = "PASS"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    determinism_in_process: bool = True
    determinism_subprocess: bool | None = None
    n_unique: int = 0
    unique_ratio: float = 0.0
    n_distinct_keys: int = 0
    mean_jaccard_distance: float = 0.0
    n_contexts: int = 0
    top_context_share: float = 0.0
    key_positions: dict[str, int] = field(default_factory=dict)
    key_position_p: float | None = None
    code_lines_observed: list[int] | None = None
    operations_observed: list[int] | None = None
    invariant_violations: int = 0
    verification: str = ""
    n_verified_variants: int = 0
    n_checks: int = 0
    n_checks_failed: int = 0
    n_checks_unavailable: int = 0
    check_failures: list[str] = field(default_factory=list)
    seconds: float = 0.0


def _evaluate(check: Check, res: RunResult) -> tuple[bool, str]:
    if res.status == "unavailable":
        return False, "unavailable"
    out = normalize_output(res.stdout)
    last = out.splitlines()[-1] if out else ""
    if check.expect == "stdout_equals":
        ok = res.status == "ok" and out == normalize_output(check.expected_stdout or "")
    elif check.expect == "stdout_differs":
        ok = res.status != "ok" or out != normalize_output(check.expected_stdout or "")
    elif check.expect == "pass":
        ok = res.status == "ok" and last.startswith("RESULT: PASS")
    else:  # fail
        ok = last.startswith("RESULT: FAIL")
    detail = "" if ok else f"status={res.status} out={out[-160:]!r} err={res.error[-160:]!r}"
    return ok, detail


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _mean_jaccard_distance(variants: list[Variant], rng: random.Random, max_pairs: int = 4000) -> float:
    toks = [_tokens(v.public_text()) for v in variants]
    n = len(toks)
    if n < 2:
        return 0.0
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    if len(pairs) > max_pairs:
        pairs = rng.sample(pairs, max_pairs)
    acc = 0.0
    for i, j in pairs:
        u = len(toks[i] | toks[j])
        acc += 1.0 - (len(toks[i] & toks[j]) / u if u else 1.0)
    return acc / len(pairs)


def _structural_errors(spec: FamilySpec, v: Variant) -> list[str]:
    """Правила связи ключа и проверок исполнением (сама истинность — в _evaluate)."""
    errs: list[str] = []
    fmt = spec.format
    names = {c.name: c for c in v.meta.checks}
    if v.meta.verification == "execution" and not v.meta.checks:
        errs.append("verification=execution, но нет проверок")
    for c in v.meta.checks:
        if c.embeds_display_code and v.code and c.runner != "sqlite" and v.code not in c.program:
            errs.append(f"{c.name}: показанный код не входит в программу дословно")
        if c.embeds_display_code and v.code and c.runner == "sqlite" and c.program != v.code:
            errs.append(f"{c.name}: SQL-запрос не совпадает с показанным")
    if fmt == "predict_output":
        eq = [c for c in v.meta.checks if c.expect == "stdout_equals"]
        if not eq:
            errs.append("predict_output: нет проверки вывода")
        for c in eq:
            if normalize_output(c.expected_stdout or "") != normalize_output(str(v.answer_key.value)):
                errs.append("predict_output: ожидаемый вывод проверки != ключ")
    if fmt == "find_bug":
        if not any(c.expect == "fail" for c in v.meta.checks) or not any(
                c.expect == "pass" for c in v.meta.checks):
            errs.append("find_bug: нужны проверки fail (дефект) и pass (исправление)")
        fixed = v.meta.params.get("fixed_code")
        if not fixed:
            errs.append("find_bug: нет params.fixed_code")
        elif changed_lines(v.code or "", fixed) != {v.answer_key.value}:
            errs.append(f"find_bug: исправление меняет строки {sorted(changed_lines(v.code or '', fixed))},"
                        f" а ключ {v.answer_key.value}")
        # Вторая равноценная строка (accept) допустима, только если исправление в ней одной
        # тоже чинит код: params.alt_fixes[строка] + проверка alt_fix:<строка> (pass).
        alt = v.meta.params.get("alt_fixes") or {}
        for a in v.answer_key.accept:
            src = alt.get(str(a))
            if not src:
                errs.append(f"find_bug: строка {a} в accept без params.alt_fixes")
            elif changed_lines(v.code or "", src) != {int(a)}:
                errs.append(f"find_bug: альтернативное исправление для строки {a} меняет строки "
                            f"{sorted(changed_lines(v.code or '', src))}")
            c = names.get(f"alt_fix:{a}")
            if c is None or c.expect != "pass":
                errs.append(f"find_bug: нет проверки alt_fix:{a} (pass)")
    if fmt in ("choose_fix", "open_book_3step"):
        groups = [("option", None)] if fmt == "choose_fix" else [("step1", 1), ("step2", 2)]
        for prefix, step in groups:
            opts = [o for o in v.options or [] if o.step == step]
            key = v.answer_key.value if step is None else v.answer_key.value[str(step)]
            for o in opts:
                c = names.get(f"{prefix}:{o.id}")
                if c is None:
                    errs.append(f"нет проверки {prefix}:{o.id}")
                    continue
                positive = c.expect in ("pass", "stdout_equals")
                if fmt == "open_book_3step" and step == 1:
                    positive = c.expect in ("fail", "stdout_differs")  # «воспроизводит дефект»
                if positive != (o.id == key):
                    errs.append(f"{prefix}:{o.id}: ожидание проверки не согласовано с ключом")
    if fmt == "mcq_concept" and v.meta.verification == "execution":
        if not any(c.expect == "stdout_equals" for c in v.meta.checks):
            errs.append("mcq_concept: нет проверки исполнением")
    n_opt = spec.invariants.n_options
    if n_opt and v.options:
        for step in sorted({o.step for o in v.options}, key=lambda s: s or 0):
            cnt = sum(1 for o in v.options if o.step == step)
            if cnt != n_opt:
                errs.append(f"шаг {step}: {cnt} вариантов вместо {n_opt}")
    return errs


def _invariant_errors(spec: FamilySpec, v: Variant) -> list[str]:
    inv = spec.invariants
    errs = []
    lang = v.meta.language
    if inv.code_lines:
        n = count_code_lines(v.code, lang)
        if not inv.code_lines[0] <= n <= inv.code_lines[1]:
            errs.append(f"code_lines={n} вне {list(inv.code_lines)}")
    if inv.operations:
        n = count_operations(v.code, lang)
        if not inv.operations[0] <= n <= inv.operations[1]:
            errs.append(f"operations={n} вне {list(inv.operations)}")
    if inv.defect_type and v.meta.defect_type != inv.defect_type:
        errs.append(f"defect_type={v.meta.defect_type} != {inv.defect_type}")
    if spec.format != "open_answer" and not spec.canary and spec.time_limit_s < 30:
        errs.append("time_limit_s слишком мал")
    return errs


def subprocess_hashes(pairs: list[tuple[str, int]], hashseed: str = "4242") -> list[str] | None:
    """Хэши вариантов, сгенерированных в отдельном процессе с другим PYTHONHASHSEED."""
    code = ("import json,sys\nfrom assessment_bank.registry import generate\n"
            "pairs=json.load(sys.stdin)\n"
            "print(json.dumps([generate(f,s).canonical_hash() for f,s in pairs]))\n")
    env = dict(os.environ, PYTHONHASHSEED=hashseed)
    root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    try:
        out = subprocess.run([sys.executable, "-c", code], input=json.dumps(pairs), text=True,
                             capture_output=True, env=env, timeout=600, check=True)
        return json.loads(out.stdout)
    except Exception:  # noqa: BLE001
        return None


def validate_family(family_id: str, n_seeds: int = 200, verify_seeds: int | None = None,
                    check_subprocess: bool = True) -> FamilyReport:
    """Проверить одно семейство (детерминизм в отдельном процессе — своим подпроцессом)."""
    rep, sample = _validate_core(family_id, n_seeds, verify_seeds)
    if check_subprocess and sample is not None:
        _apply_subprocess(rep, sample, subprocess_hashes([(family_id, s) for s, _h in sample]))
    return _finalize(rep)


def _apply_subprocess(rep: FamilyReport, sample: list[tuple[int, str]], hs: list[str] | None) -> None:
    rep.determinism_subprocess = hs is not None and hs == [h for _s, h in sample]
    if not rep.determinism_subprocess:
        rep.errors.insert(0, "генерация в отдельном процессе даёт другой результат")


def _finalize(rep: FamilyReport) -> FamilyReport:
    if rep.status != "FAIL" or rep.errors:
        rep.status = "FAIL" if rep.errors else ("WARN" if rep.warnings else "PASS")
    return rep


def _validate_core(family_id: str, n_seeds: int = 200,
                   verify_seeds: int | None = None) -> tuple[FamilyReport, list[tuple[int, str]] | None]:
    """Всё, кроме детерминизма в отдельном процессе; вторым значением — (seed, хэш) первых 20 вариантов
    для этой проверки (None, если ни один вариант не сгенерирован)."""
    t0 = time.time()
    spec = registry.get_spec(family_id)
    rep = FamilyReport(family_id=family_id, title=spec.title, direction=spec.direction,
                       format=spec.format, target_grades=list(spec.target_grades),
                       canary=spec.canary, n_seeds=n_seeds)
    seeds = list(range(1, n_seeds + 1))
    variants: list[Variant] = []
    for s in seeds:
        try:
            variants.append(registry.generate(family_id, s))
        except Exception as exc:  # noqa: BLE001
            rep.errors.append(f"seed {s}: ошибка генерации: {type(exc).__name__}: {exc}"[:300])
    if not variants:
        rep.status = "FAIL"
        return rep, None
    # детерминизм
    for v in variants[: min(50, len(variants))]:
        if registry.generate(family_id, v.meta.seed).canonical_hash() != v.canonical_hash():
            rep.determinism_in_process = False
            rep.errors.append(f"seed {v.meta.seed}: недетерминированная генерация")
            break
    sample = [(v.meta.seed, v.canonical_hash()) for v in variants[:20]]
    # уникальность и разнообразие
    fps = [v.fingerprint() for v in variants]
    rep.n_unique = len(set(fps))
    rep.unique_ratio = rep.n_unique / len(variants)
    keys = [json.dumps(v.answer_key.value, ensure_ascii=False, sort_keys=True) for v in variants]
    rep.n_distinct_keys = len(set(keys))
    rep.mean_jaccard_distance = round(_mean_jaccard_distance(variants, random.Random(7)), 4)
    ctx = Counter(v.meta.context for v in variants)
    rep.n_contexts = len(ctx)
    rep.top_context_share = round(max(ctx.values()) / len(variants), 3)
    if spec.format in ("choose_fix", "mcq_concept"):
        pos = Counter(v.answer_key.value for v in variants)
    elif spec.format == "open_book_3step":
        pos = Counter()
        for v in variants:
            pos.update([v.answer_key.value["1"], v.answer_key.value["2"]])
    else:
        pos = Counter()
    if pos:
        letters = sorted({o.id for v in variants for o in (v.options or [])})
        rep.key_positions = {k: pos.get(k, 0) for k in letters}
        obs = [pos.get(k, 0) for k in letters]
        rep.key_position_p = round(float(stats.chisquare(obs).pvalue), 4)
    # инварианты и структура
    cl = [count_code_lines(v.code, v.meta.language) for v in variants if v.code]
    ops = [count_operations(v.code, v.meta.language) for v in variants if v.code]
    rep.code_lines_observed = [min(cl), max(cl)] if cl else None
    rep.operations_observed = [min(ops), max(ops)] if ops else None
    inv_examples: list[str] = []
    struct_examples: list[str] = []
    n_struct = 0
    for v in variants:
        errs = _invariant_errors(spec, v)
        if errs:
            rep.invariant_violations += 1
            if len(inv_examples) < 3:
                inv_examples.append(f"seed {v.meta.seed}: {'; '.join(errs)}")
        serrs = _structural_errors(spec, v)
        if serrs:
            n_struct += 1
            if len(struct_examples) < 3:
                struct_examples.append(f"seed {v.meta.seed}: {'; '.join(serrs)}"[:300])
    if rep.invariant_violations:
        rep.errors.append(f"нарушены инварианты в {rep.invariant_violations} вариантах")
    if n_struct:
        rep.errors.append(f"ошибки структуры ключа/проверок в {n_struct} вариантах")
    rep.errors.extend(inv_examples + struct_examples)
    # проверка ключей исполнением
    rep.verification = Counter(v.meta.verification for v in variants).most_common(1)[0][0]
    to_verify = variants if verify_seeds is None else variants[:verify_seeds]
    checks: list[tuple[int, Check]] = [(v.meta.seed, c) for v in to_verify for c in v.meta.checks]
    rep.n_verified_variants = sum(1 for v in to_verify if v.meta.checks)
    rep.n_checks = len(checks)
    if checks:
        results = run_checks([c for _, c in checks])
        for (seed, c), r in zip(checks, results):
            ok, detail = _evaluate(c, r)
            if detail == "unavailable":
                rep.n_checks_unavailable += 1
            elif not ok:
                rep.n_checks_failed += 1
                if len(rep.check_failures) < 5:
                    rep.check_failures.append(f"seed {seed} {c.name}: {detail}"[:400])
    # итог
    if rep.n_checks_failed:
        rep.errors.append(f"провалено проверок ключа: {rep.n_checks_failed} из {rep.n_checks}")
    if spec.format == "open_answer" and rep.n_unique >= min(OPEN_MIN_DISTINCT, len(variants) // 2):
        # открытый вопрос оценивается по рубрике рассуждения: число различных формулировок
        # ограничено естественным образом, требуем лишь достаточный запас для ротации
        if rep.unique_ratio < UNIQUE_WARN:
            rep.warnings.append(f"открытый формат: {rep.n_unique} различных формулировок на "
                                f"{len(variants)} seed (допустимо, минимум {OPEN_MIN_DISTINCT})")
    elif rep.unique_ratio < UNIQUE_FAIL:
        rep.errors.append(f"уникальных вариантов {rep.unique_ratio:.0%} < {UNIQUE_FAIL:.0%}")
    elif rep.unique_ratio < UNIQUE_WARN:
        rep.warnings.append(f"уникальных вариантов {rep.unique_ratio:.1%}")
    if rep.mean_jaccard_distance < JACCARD_WARN:
        rep.warnings.append(f"низкое поверхностное разнообразие ({rep.mean_jaccard_distance:.2f})")
    if rep.top_context_share > CONTEXT_SHARE_WARN:
        rep.warnings.append(f"один контекст занимает {rep.top_context_share:.0%} вариантов")
    if rep.key_position_p is not None and rep.key_position_p < 0.01:
        rep.warnings.append(f"неравномерная позиция правильного ответа (p={rep.key_position_p})")
    if rep.n_checks_unavailable:
        rep.warnings.append(f"{rep.n_checks_unavailable} проверок пропущено: нет исполнителя")
    if rep.verification == "reference_table":
        rep.warnings.append("ключ сверен со справочной таблицей, исполнение невозможно")
    rep.status = "FAIL" if rep.errors else ("WARN" if rep.warnings else "PASS")
    rep.seconds = round(time.time() - t0, 2)
    return rep, sample


def _validate_chunk(fids: list[str], n_seeds: int, verify_seeds: int | None,
                    check_subprocess: bool = True) -> list[dict[str, Any]]:
    """Пачка семейств в одном рабочем процессе. Детерминизм «в отдельном процессе» проверяется ОДНИМ подпроцессом
    (другой PYTHONHASHSEED) на всю пачку — вместо подпроцесса на каждое семейство; если пачка в подпроцессе не
    сгенерировалась целиком, каждое семейство пачки перепроверяется своим подпроцессом (как раньше)."""
    done: list[tuple[FamilyReport, list[tuple[int, str]] | None]] = []
    for fid in fids:
        try:
            done.append(_validate_core(fid, n_seeds, verify_seeds))
        except Exception as exc:  # noqa: BLE001 — сломанное семейство не роняет пачку
            spec = registry.load_specs().get(fid)
            rep = FamilyReport(family_id=fid, title=getattr(spec, "title", fid),
                               direction=getattr(spec, "direction", fid.split(".")[0]),
                               format=getattr(spec, "format", "?"),
                               target_grades=list(getattr(spec, "target_grades", []) or []),
                               canary=bool(getattr(spec, "canary", False)), n_seeds=n_seeds, status="FAIL",
                               errors=[f"валидатор: {type(exc).__name__}: {exc}"[:300]])
            done.append((rep, None))
    if check_subprocess:
        todo = [(rep, sample) for rep, sample in done if sample is not None]
        pairs = [(rep.family_id, s) for rep, sample in todo for s, _h in sample]
        hs = subprocess_hashes(pairs) if pairs else []
        if hs is not None and len(hs) == len(pairs):
            i = 0
            for rep, sample in todo:
                _apply_subprocess(rep, sample, hs[i:i + len(sample)])
                i += len(sample)
        else:
            for rep, sample in todo:
                _apply_subprocess(rep, sample, subprocess_hashes([(rep.family_id, s) for s, _h in sample]))
    return [asdict(_finalize(rep)) for rep, _sample in done]


def default_jobs() -> int:
    """Число рабочих процессов: BANK_VALIDATE_JOBS или доступные процессу ядра (не ядра хоста), не больше 32."""
    env = os.environ.get("BANK_VALIDATE_JOBS")
    if env:
        return max(1, int(env))
    try:
        n = len(os.sched_getaffinity(0))
    except AttributeError:  # не Linux
        n = os.cpu_count() or 1
    return max(1, min(32, n))


def validate_bank(n_seeds: int = 200, verify_seeds: int | None = None,
                  families: list[str] | None = None, progress: bool = False,
                  jobs: int | None = None, chunk: int = 12) -> dict[str, Any]:
    """Валидация банка на всех ядрах: семейства режутся на пачки по ``chunk`` и раздаются
    ``concurrent.futures.ProcessPoolExecutor`` (``jobs`` процессов, по умолчанию — :func:`default_jobs`).
    Результат не зависит от числа процессов: порядок отчётов — порядок ``families`` / ``load_specs()``."""
    t0 = time.time()
    fids = families or list(registry.load_specs())
    jobs = default_jobs() if jobs is None else max(1, int(jobs))
    chunks = [fids[i:i + chunk] for i in range(0, len(fids), chunk)]
    by_fid: dict[str, dict[str, Any]] = {}

    def show(rows: list[dict[str, Any]]) -> None:
        for r in rows:
            by_fid[r["family_id"]] = r
            if progress:
                print(f"  {r['status']:4} {r['family_id']:45} uniq={r['unique_ratio']:.3f} checks={r['n_checks']}"
                      f" failed={r['n_checks_failed']} {r['seconds']:.1f}s", flush=True)

    if jobs == 1 or len(chunks) <= 1:
        for c in chunks:
            show(_validate_chunk(c, n_seeds, verify_seeds))
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        with ProcessPoolExecutor(max_workers=min(jobs, len(chunks))) as ex:
            futs = [ex.submit(_validate_chunk, c, n_seeds, verify_seeds) for c in chunks]
            for f in as_completed(futs):
                show(f.result())
    reports = [FamilyReport(**by_fid[fid]) for fid in fids]
    summary = {
        "n_families": len(reports),
        "n_variants_generated": sum(r.n_seeds for r in reports),
        "n_unique_variants": sum(r.n_unique for r in reports),
        "n_checks": sum(r.n_checks for r in reports),
        "n_checks_failed": sum(r.n_checks_failed for r in reports),
        "status": Counter(r.status for r in reports),
        # число семейств FAIL — по нему CLI возвращает код выхода (раньше ключа не было, и validate всегда давал 0)
        "n_fail": sum(1 for r in reports if r.status == "FAIL"),
        "n_warn": sum(1 for r in reports if r.status == "WARN"),
        "by_direction": Counter(r.direction for r in reports),
        "by_format": Counter(r.format for r in reports),
        "seconds": round(time.time() - t0, 1),
        "jobs": jobs,
    }
    return {"summary": summary, "families": [asdict(r) for r in reports]}


def report_markdown(result: dict[str, Any]) -> str:
    s = result["summary"]
    lines = ["# Отчёт валидатора банка заданий", "",
             f"Семейств: {s['n_families']}; вариантов сгенерировано: {s['n_variants_generated']}; "
             f"уникальных: {s['n_unique_variants']}; проверок ключа исполнением: {s['n_checks']}, "
             f"провалено: {s['n_checks_failed']}; время: {s['seconds']} с.", "",
             f"Статусы: {dict(s['status'])}", "",
             "| Семейство | Формат | Грейды | Статус | Уник. | Ключей | Жаккар | Контекстов | "
             "Строк кода | Операций | Проверок (провал) | Замечания |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in result["families"]:
        notes = "; ".join(r["errors"][:2] + r["warnings"][:2]) or "—"
        flag = " (канарейка)" if r["canary"] else ""
        cl = "–".join(map(str, r["code_lines_observed"])) if r["code_lines_observed"] else "—"
        op = "–".join(map(str, r["operations_observed"])) if r["operations_observed"] else "—"
        lines.append(
            f"| `{r['family_id']}`{flag} | {r['format']} | {', '.join(r['target_grades'])} | "
            f"{r['status']} | {r['unique_ratio']:.3f} | {r['n_distinct_keys']} | "
            f"{r['mean_jaccard_distance']:.2f} | {r['n_contexts']} | {cl} | {op} | "
            f"{r['n_checks']} ({r['n_checks_failed']}) | {notes} |")
    return "\n".join(lines) + "\n"
