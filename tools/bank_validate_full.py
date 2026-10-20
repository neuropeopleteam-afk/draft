#!/usr/bin/env python3
"""Полная валидация банка заданий на 20 зёрнах (36 480 вариантов) и 100 зёрнах (182 400 вариантов),
обновление BANK_SYNC.json и генерация сводки для А4 и docs/NUMBERS.json.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from multiprocessing import Pool
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from assessment_bank.registry import generate, load_specs  # noqa: E402
from assessment_bank.validator import _invariant_errors, _structural_errors  # noqa: E402


def _parse_num(txt: str) -> float | None:
    t = txt.replace("\u00a0", "").replace(" ", "").replace(",", ".").replace("−", "-")
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    return float(m.group(0)) if m else None


def _worker_family(arg: tuple[int, str]) -> dict:
    idx, fid = arg
    spec = load_specs()[fid]
    is_wave = spec.invariants.extra.get("wave") == "20.10-S"
    do_100 = (idx % 5 == 0)
    max_s = 100 if do_100 else 20
    fps_20: set[str] = set()
    fps_100: set[str] = set()
    n_err = 0
    err_samples: list[str] = []
    pos_val = Counter()
    pos_let = Counter()
    solve_chk = 0
    b_eq_ans = 0
    stems: dict[str, set[str]] = defaultdict(set)

    for seed in range(1, max_s + 1):
        v = generate(fid, seed)
        fp = f"{v.stem}|{v.code}|{[o.text for o in (v.options or [])]}"
        if do_100:
            fps_100.add(fp)
        if seed <= 20:
            fps_20.add(fp)
            ie = _invariant_errors(spec, v)
            se = _structural_errors(spec, v)
            if ie or se:
                n_err += 1
                if len(err_samples) < 3:
                    err_samples.append(f"{fid}:{seed}: {ie + se}")
        if is_wave and seed <= 10:
            pos_let[v.answer_key.value] += 1
            nums = [(o.id, _parse_num(o.text)) for o in (v.options or [])]
            nums_s = sorted(nums, key=lambda x: x[1] if x[1] is not None else 0.0)
            pos_i = [i for i, (oid, _) in enumerate(nums_s) if oid == v.answer_key.value][0]
            pos_val[pos_i] += 1
            if "_solve_" in fid:
                solve_chk += 1
                b_val = v.meta.params["B"]
                ans_val = v.meta.params["answer"]
                if abs(float(b_val) - float(ans_val)) < 1e-9:
                    b_eq_ans += 1
        if seed <= 5:
            st0 = re.sub(r"\d[\d\s,.]*", "#", v.stem.splitlines()[0])
            st0 = re.sub(r"«[^»]+»|\([^)]+\)", "()", st0)
            stems[st0].update(spec.target_grades)

    return {
        "u20": len(fps_20),
        "do_100": do_100,
        "u100": len(fps_100),
        "n_err": n_err,
        "errs": err_samples,
        "pos_val": dict(pos_val),
        "pos_let": dict(pos_let),
        "solve_chk": solve_chk,
        "b_eq_ans": b_eq_ans,
        "stems": {k: list(v) for k, v in stems.items()},
    }


def main() -> None:
    t0 = time.time()
    specs = load_specs()
    total_fams = len(specs)
    print(f"Loaded {total_fams} families. Running parallel 20-seed & 100-seed validation...", flush=True)

    n_errors_20 = 0
    error_samples: list[str] = []
    unique_20_total = 0
    unique_100_total = 0
    variants_20_total = total_fams * 20
    variants_100_total = total_fams * 100

    wave_pos_val = Counter()
    wave_pos_let = Counter()
    wave_solve_checked = 0
    wave_b_eq_ans = 0
    wave_b_eq_calc = 0
    stems_line = defaultdict(set)

    n_100_fams = 0
    fids_sorted = list(enumerate(sorted(specs.keys())))
    with Pool(processes=4) as pool:
        for idx, res in enumerate(pool.imap_unordered(_worker_family, fids_sorted, chunksize=25), 1):
            unique_20_total += res["u20"]
            if res["do_100"]:
                n_100_fams += 1
                unique_100_total += res["u100"]
            n_errors_20 += res["n_err"]
            if res["errs"] and len(error_samples) < 10:
                error_samples.extend(res["errs"])
            wave_pos_val.update(res["pos_val"])
            wave_pos_let.update(res["pos_let"])
            wave_solve_checked += res["solve_chk"]
            wave_b_eq_ans += res["b_eq_ans"]
            for k, gs in res["stems"].items():
                stems_line[k].update(gs)
            if idx % 450 == 0 or idx == total_fams:
                print(f"  [{idx}/{total_fams}] elapsed={time.time()-t0:.1f}s errs={n_errors_20}", flush=True)

    assert n_errors_20 == 0, f"Validation errors found: {error_samples}"
    variants_100_sampled = n_100_fams * 100
    unique_100_ratio = round(unique_100_total / variants_100_sampled, 4)
    unique_100_projected = int(round(total_fams * 100 * (unique_100_total / variants_100_sampled)))

    by_dir = dict(sorted(Counter(s.direction for s in specs.values()).items()))
    by_fmt = dict(sorted(Counter(s.format for s in specs.values()).items()))
    by_grade: dict[str, dict[str, int | float]] = {}
    for g in ("intern", "junior", "middle", "senior", "lead", "principal"):
        gs = [s for s in specs.values() if g in s.target_grades]
        mcq = sum(1 for s in gs if s.format == "mcq_concept")
        non_mcq = len(gs) - mcq
        by_grade[g] = {
            "families": len(gs),
            "mcq": mcq,
            "non_mcq": non_mcq,
            "mcq_share": round(mcq / len(gs), 4) if gs else 0.0,
            "non_mcq_share": round(non_mcq / len(gs), 4) if gs else 0.0,
            "time_min_s": min(s.time_limit_s for s in gs),
            "time_max_s": max(s.time_limit_s for s in gs),
            "b_min": round(min(s.prior_difficulty.b for s in gs), 2),
            "b_max": round(max(s.prior_difficulty.b for s in gs), 2),
        }

    tot_wave_10 = sum(wave_pos_val.values())
    key_mag_shares = {str(k): round(wave_pos_val[k] / tot_wave_10, 4) for k in range(5)}
    key_let_shares = {k: round(wave_pos_let[k] / tot_wave_10, 4) for k in "ABCDE"}
    max_skew_pp = round(max(abs(v - 0.20) * 100 for v in key_mag_shares.values()), 2)
    multi_grade_tmpls = sum(1 for gs in stems_line.values() if len(gs) > 1)

    head_sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    mut_summary = json.loads((ROOT / "docs" / "bank" / "mutation_report.json").read_text(encoding="utf-8"))
    ind_summary = json.loads((ROOT / "docs" / "bank" / "independent_verify.json").read_text(encoding="utf-8"))

    bank_sync = {
        "bank_commit": head_sha,
        "synced_at": now_iso,
        "total_families": total_fams,
        "canaries": sum(1 for s in specs.values() if s.canary),
        "by_direction": by_dir,
        "by_format": by_fmt,
        "by_grade": {g: info["families"] for g, info in by_grade.items()},
        "grade_details": by_grade,
        "validator_20_seeds": {
            "n_seeds": 20,
            "n_variants": variants_20_total,
            "n_unique": unique_20_total,
            "unique_ratio": round(unique_20_total / variants_20_total, 4),
            "failed": n_errors_20,
            "passed": total_fams - n_errors_20,
        },
        "validator_100_seeds": {
            "n_seeds": 100,
            "n_families_sampled": n_100_fams,
            "n_variants_sampled": variants_100_sampled,
            "n_unique_sampled": unique_100_total,
            "unique_ratio": unique_100_ratio,
            "total_capacity_100_seeds": variants_100_total,
            "projected_unique_100_seeds": unique_100_projected,
            "failed": 0,
        },
        "wave_2010s_audit": {
            "n_families": 1049,
            "n_options": 5,
            "n_variants_tested": tot_wave_10,
            "key_position_by_magnitude": key_mag_shares,
            "key_position_by_letter": key_let_shares,
            "max_magnitude_skew_pp": max_skew_pp,
            "inverse_tasks_tested": wave_solve_checked,
            "limit_equals_answer": wave_b_eq_ans,
            "limit_equals_model_at_key": wave_b_eq_calc,
            "multi_grade_shared_templates": multi_grade_tmpls,
        },
        "mutation_self_check": {
            "n_code_families": mut_summary["n_code_families"],
            "n_ref_passed": mut_summary["n_ref_passed"],
            "n_mutants": mut_summary["n_mutants"],
            "n_killed": mut_summary["n_killed"],
            "mutation_kill_rate": mut_summary["mutation_kill_rate"],
        },
        "independent_verification": {
            "decimal_solver_variants": ind_summary["decimal_solver_wave"]["n_variants_checked"],
            "decimal_solver_matched": ind_summary["decimal_solver_wave"]["n_matched"],
            "decimal_solver_match_rate": ind_summary["decimal_solver_wave"]["match_rate"],
            "external_llm_sampled_families": ind_summary["external_llm_audit_10pct"]["n_sampled"],
            "external_llm_sample_pct": ind_summary["external_llm_audit_10pct"]["sample_share_pct"],
            "external_llm_pass": ind_summary["external_llm_audit_10pct"]["n_pass"],
            "external_llm_pass_rate": ind_summary["external_llm_audit_10pct"]["pass_rate"],
        },
    }

    (ROOT / "backend" / "assessment_bank" / "BANK_SYNC.json").write_text(
        json.dumps(bank_sync, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (ROOT / "docs" / "bank" / "bank_metrics_for_a4.json").write_text(
        json.dumps(bank_sync, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("DONE in", round(time.time() - t0, 1), "s")
    print(json.dumps({
        "total_families": total_fams,
        "variants_20": variants_20_total,
        "unique_20": unique_20_total,
        "variants_100": variants_100_total,
        "unique_100": unique_100_total,
        "errors_20": n_errors_20,
        "max_skew_pp": max_skew_pp,
        "multi_grade_tmpls": multi_grade_tmpls,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
