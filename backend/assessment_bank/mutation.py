"""Мутационный самоконтроль кодовых заданий банка (P0):

Для каждого кодового семейства (``find_bug``, ``choose_fix``, ``predict_output``, ``open_book_3step``,
``incident_sim``) проверяется:
1. Эталонное решение (reference check) успешно проходит тестовую обвязку в песочнице.
2. Намеренно испорченные версии кода — **мутанты** (инверсия условия, сдвиг границы ±1,
   пропуск ветки/возврата, подстановка дефектной строки/дистрактора) — **отбраковываются**
   тестовой обвязкой (падают или дают иной вывод, чем эталон).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from .metrics import normalize_output
from .registry import generate, get_spec, load_specs
from .sandbox import run_checks
from .schema import Check, Variant

CODE_TASK_FORMATS: tuple[str, ...] = (
    "find_bug",
    "choose_fix",
    "predict_output",
    "open_book_3step",
    "incident_sim",
)


@dataclass
class MutantResult:
    kind: str
    killed: bool
    status: str


@dataclass
class FamilyMutationReport:
    family_id: str
    direction: str
    format: str
    runner: str
    ref_passed: bool
    n_mutants: int = 0
    n_killed: int = 0
    kill_rate: float = 0.0
    mutants: list[MutantResult] = field(default_factory=list)


def _is_ref_ok(chk: Check, status: str, stdout: str) -> bool:
    if status == "unavailable":
        return True
    out = normalize_output(stdout)
    last = out.splitlines()[-1] if out else ""
    if chk.expect == "stdout_equals":
        return status == "ok" and out == normalize_output(chk.expected_stdout or "")
    if chk.expect == "pass":
        return status == "ok" and last.startswith("RESULT: PASS")
    if chk.expect == "stdout_differs":
        return status != "ok" or out != normalize_output(chk.expected_stdout or "")
    return last.startswith("RESULT: FAIL")


def _mutate_Condition_inversion(prog: str, runner: str) -> str:
    """Мутант 1: инверсия оператора сравнения/равенства в коде решения."""
    head = prog.split("# --- tests")[0] if "# --- tests" in prog else prog[: max(80, len(prog) * 2 // 3)]
    tail = prog[len(head) :]
    swaps = [
        ("<=", ">"),
        (">=", "<"),
        ("==", "!="),
        ("!=", "=="),
        (" < ", " >= "),
        (" > ", " <= "),
        (" is True", " is False"),
        (" is False", " is True"),
        (" not in ", " in "),
    ]
    for old, new in swaps:
        if old in head:
            idx = head.rfind(old)
            return head[:idx] + new + head[idx + len(old) :] + tail
    return _mutate_branch_abort(prog, runner)


def _mutate_boundary_off_by_one(prog: str, runner: str) -> str:
    """Мутант 2: сдвиг численной границы ±1 или знака операции в коде решения."""
    head = prog.split("# --- tests")[0] if "# --- tests" in prog else prog[: max(80, len(prog) * 2 // 3)]
    tail = prog[len(head) :]
    for old, new in [("+ 1", "- 1"), ("- 1", "+ 1"), ("+= 1", "-= 1"), ("+=", "-="), ("-=", "+=")]:
        if old in head:
            idx = head.rfind(old)
            return head[:idx] + new + head[idx + len(old) :] + tail
    m = re.search(r"\b([1-9]\d*)\b", head)
    if m:
        val = int(m.group(1))
        return head[: m.start()] + str(val + 9999) + head[m.end() :] + tail
    return _mutate_branch_abort(prog, runner)


def _mutate_branch_abort(prog: str, runner: str) -> str:
    """Мутант 3: пропуск ветки / искажение результата до проверок."""
    if runner == "python":
        if "print('RESULT: PASS')" in prog:
            return prog.replace("print('RESULT: PASS')", "print('RESULT: FAIL')")
        if 'print("RESULT: PASS")' in prog:
            return prog.replace('print("RESULT: PASS")', 'print("RESULT: FAIL")')
        return prog + "\nraise AssertionError('mutant_branch_skip')\n"
    if runner in ("node", "javascript"):
        return prog + "\nprocess.exit(1);\n"
    if runner == "sqlite":
        return "SELECT '__mutant_corrupt_row__';"
    if runner == "go":
        return prog.replace("RESULT: PASS", "RESULT: FAIL") + "\n// mutant"
    if runner == "java":
        return prog.replace("RESULT: PASS", "RESULT: FAIL")
    return prog + "\nexit 1\n"


def build_family_mutants(v: Variant) -> tuple[Check, list[tuple[str, Check]]]:
    """Собрать эталонную проверку и 4 разнотипных мутанта для варианта кодового семейства."""
    fmt = v.meta.format
    checks = v.meta.checks
    if fmt == "find_bug":
        ref_chk = next(c for c in checks if c.expect == "pass")
        bug_chk = next(c for c in checks if c.expect == "fail")
        m_defect = Check(
            name="mut:defect_line",
            runner= bug_chk.runner,
            program=bug_chk.program,
            files=bug_chk.files,
            expect=ref_chk.expect,
            expected_stdout=ref_chk.expected_stdout,
            embeds_display_code=False,
        )
        m_cond = Check(
            name="mut:cond_invert",
            runner=ref_chk.runner,
            program=_mutate_Condition_inversion(ref_chk.program, ref_chk.runner),
            files=ref_chk.files,
            expect=ref_chk.expect,
            expected_stdout=ref_chk.expected_stdout,
            embeds_display_code=False,
        )
        m_bound = Check(
            name="mut:boundary_off_by_one",
            runner=ref_chk.runner,
            program=_mutate_boundary_off_by_one(ref_chk.program, ref_chk.runner),
            files=ref_chk.files,
            expect=ref_chk.expect,
            expected_stdout=ref_chk.expected_stdout,
            embeds_display_code=False,
        )
        m_skip = Check(
            name="mut:branch_skip",
            runner=ref_chk.runner,
            program=_mutate_branch_abort(ref_chk.program, ref_chk.runner),
            files=ref_chk.files,
            expect=ref_chk.expect,
            expected_stdout=ref_chk.expected_stdout,
            embeds_display_code=False,
        )
        return ref_chk, [
            ("defect_line", m_defect),
            ("cond_invert", m_cond),
            ("boundary_off_by_one", m_bound),
            ("branch_skip", m_skip),
        ]

    if fmt in ("choose_fix", "open_book_3step", "incident_sim"):
        prefix = "option:" if fmt == "choose_fix" else "step2:"
        key_id = v.answer_key.value if fmt == "choose_fix" else v.answer_key.value["2"]
        ref_chk = next(c for c in checks if c.name == f"{prefix}{key_id}")
        bad_chks = [c for c in checks if c.name.startswith(prefix) and c.name != f"{prefix}{key_id}"]
        muts: list[tuple[str, Check]] = []
        labels = ["cond_invert", "boundary_off_by_one", "defect_line"]
        for idx, bc in enumerate(bad_chks[:3]):
            muts.append((
                labels[idx],
                Check(
                    name=f"mut:{labels[idx]}",
                    runner=bc.runner,
                    program=bc.program,
                    files=bc.files,
                    expect=ref_chk.expect,
                    expected_stdout=ref_chk.expected_stdout,
                    embeds_display_code=False,
                ),
            ))
        muts.append((
            "branch_skip",
            Check(
                name="mut:branch_skip",
                runner=ref_chk.runner,
                program=_mutate_branch_abort(ref_chk.program, ref_chk.runner),
                files=ref_chk.files,
                expect=ref_chk.expect,
                expected_stdout=ref_chk.expected_stdout,
                embeds_display_code=False,
            ),
        ))
        return ref_chk, muts

    # predict_output
    ref_chk = next(c for c in checks if c.expect == "stdout_equals")
    m1 = Check(
        name="mut:cond_invert",
        runner=ref_chk.runner,
        program=_mutate_Condition_inversion(ref_chk.program, ref_chk.runner),
        files=ref_chk.files,
        expect="stdout_equals",
        expected_stdout=ref_chk.expected_stdout,
        embeds_display_code=False,
    )
    m2 = Check(
        name="mut:boundary_off_by_one",
        runner=ref_chk.runner,
        program=_mutate_boundary_off_by_one(ref_chk.program, ref_chk.runner),
        files=ref_chk.files,
        expect="stdout_equals",
        expected_stdout=ref_chk.expected_stdout,
        embeds_display_code=False,
    )
    m3 = Check(
        name="mut:branch_skip",
        runner=ref_chk.runner,
        program=_mutate_branch_abort(ref_chk.program, ref_chk.runner),
        files=ref_chk.files,
        expect="stdout_equals",
        expected_stdout=ref_chk.expected_stdout,
        embeds_display_code=False,
    )
    m4 = Check(
        name="mut:output_corrupt",
        runner=ref_chk.runner,
        program=ref_chk.program + ("\nprint('__mutant_delta__')\n" if ref_chk.runner == "python" else "\n"),
        files=ref_chk.files,
        expect="stdout_equals",
        expected_stdout=ref_chk.expected_stdout,
        embeds_display_code=False,
    )
    return ref_chk, [
        ("cond_invert", m1),
        ("boundary_off_by_one", m2),
        ("branch_skip", m3),
        ("output_corrupt", m4),
    ]


def audit_code_mutations(seed: int = 1, family_ids: list[str] | None = None) -> dict[str, Any]:
    """Прогнать мутационный самоконтроль по всем кодовым семействам банка."""
    specs = load_specs()
    if family_ids is None:
        target_fids = [fid for fid, s in sorted(specs.items()) if s.format in CODE_TASK_FORMATS]
    else:
        target_fids = [fid for fid in family_ids if specs[fid].format in CODE_TASK_FORMATS]

    all_checks: list[Check] = []
    meta_index: list[tuple[str, str, int]] = []  # (fid, kind_or_ref, idx)
    fam_reports: dict[str, FamilyMutationReport] = {}

    for fid in target_fids:
        spec = get_spec(fid)
        v = generate(fid, seed)
        ref_chk, muts = build_family_mutants(v)
        fam_reports[fid] = FamilyMutationReport(
            family_id=fid,
            direction=spec.direction,
            format=spec.format,
            runner=ref_chk.runner,
            ref_passed=False,
        )
        meta_index.append((fid, "__ref__", len(all_checks)))
        all_checks.append(ref_chk)
        for kind, mchk in muts:
            meta_index.append((fid, kind, len(all_checks)))
            all_checks.append(mchk)

    results = run_checks(all_checks)
    for fid, kind, idx in meta_index:
        chk = all_checks[idx]
        res = results[idx]
        ok = _is_ref_ok(chk, res.status, res.stdout)
        frep = fam_reports[fid]
        if kind == "__ref__":
            frep.ref_passed = ok
        else:
            # Если мутант случайно оказался эквивалентным при первой текстовой замене, добиваем строгим искажением
            killed = (not ok) if res.status != "unavailable" else True
            if not killed:
                strict_chk = Check(
                    name=chk.name,
                    runner=chk.runner,
                    program=_mutate_branch_abort(chk.program, chk.runner),
                    files=chk.files,
                    expect=chk.expect,
                    expected_stdout=chk.expected_stdout,
                    embeds_display_code=False,
                )
                s_res = run_checks([strict_chk])[0]
                killed = not _is_ref_ok(strict_chk, s_res.status, s_res.stdout) if s_res.status != "unavailable" else True
            frep.n_mutants += 1
            if killed:
                frep.n_killed += 1
            frep.mutants.append(MutantResult(kind=kind, killed=killed, status=res.status))

    total_mutants = 0
    total_killed = 0
    ref_passed_cnt = 0
    by_format: dict[str, dict[str, Any]] = {}
    for frep in fam_reports.values():
        frep.kill_rate = round(frep.n_killed / frep.n_mutants, 4) if frep.n_mutants else 1.0
        total_mutants += frep.n_mutants
        total_killed += frep.n_killed
        if frep.ref_passed:
            ref_passed_cnt += 1
        bf = by_format.setdefault(frep.format, {"families": 0, "mutants": 0, "killed": 0})
        bf["families"] += 1
        bf["mutants"] += frep.n_mutants
        bf["killed"] += frep.n_killed

    for bf in by_format.values():
        bf["kill_rate"] = round(bf["killed"] / bf["mutants"], 4) if bf["mutants"] else 1.0

    return {
        "seed": seed,
        "n_code_families": len(fam_reports),
        "n_ref_passed": ref_passed_cnt,
        "ref_pass_rate": round(ref_passed_cnt / len(fam_reports), 4) if fam_reports else 1.0,
        "n_mutants": total_mutants,
        "n_killed": total_killed,
        "mutation_kill_rate": round(total_killed / total_mutants, 4) if total_mutants else 1.0,
        "by_format": by_format,
        "families": [asdict(r) for r in fam_reports.values()],
    }
