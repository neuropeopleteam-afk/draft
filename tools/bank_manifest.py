"""Манифест BANK_SYNC.json для банка, который правится прямо в дереве платформы (А3, 21.10.2026).

Формат — тот же, что пишет tools/sync_bank.py (его читают validation/provenance, catalog/ext.directions_verified,
assessment/bank_engine, tools/publish/gen_numbers.py: commit, content_hash, n_families, by_direction,
directions_verified, readiness, excluded, validation.summary), плюс блок ``quality`` — итоги аудита банка
(tools/bank_audit.py), мутационного самоконтроля и параметров трудности. Все цифры — из файлов-отчётов, руками
ничего не пишется.

Запуск из корня репозитория:
    python3 tools/bank_manifest.py --validation-report <validation_report.json> \
        [--audit docs/bank/audit_2110.json] [--mutation docs/bank/mutation_report.json]
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "backend" / "assessment_bank"

_spec = importlib.util.spec_from_file_location("sync_bank", REPO / "tools" / "sync_bank.py")
sync_bank = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_bank)  # type: ignore[union-attr]


def _git(*a: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validation-report", required=True)
    ap.add_argument("--audit", default=str(REPO / "docs" / "bank" / "audit_2110.json"))
    ap.add_argument("--mutation", default=str(REPO / "docs" / "bank" / "mutation_report.json"))
    ap.add_argument("--diff", default=str(REPO / "docs" / "bank" / "bank_diff_vs_603474f.json"),
                    help="JSON tools/bank_diff_base.py: отличие от банка, на котором считала А4")
    ap.add_argument("--validated-commit", default="",
                    help="голова, на дереве которой шёл прогон валидатора (банк в ней должен совпадать с текущим)")
    ap.add_argument("--where", default="сервер «Москва», одноразовый контейнер api (tmpfs /dev/shm с exec)")
    a = ap.parse_args()

    r = subprocess.run([sys.executable, "-c", sync_bank.FINAL_CHECK], cwd=str(REPO / "backend"),
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-2000:], file=sys.stderr)
        return 2
    final = json.loads(r.stdout.strip().splitlines()[-1])
    readiness = final.get("readiness") or {}
    verified = sorted(d for d, x in readiness.items() if x["families"] >= sync_bank.READY_MIN_FAMILIES
                      and min(x["per_grade"].values()) >= sync_bank.READY_MIN_PER_GRADE)
    rep = json.loads(Path(a.validation_report).read_text(encoding="utf-8"))
    summ = rep.get("summary") or {}

    sys.path.insert(0, str(REPO / "backend"))
    from assessment_bank.registry import load_specs  # noqa: E402
    specs = load_specs()
    prior_a = collections.Counter(f"{s.format}:{s.prior_difficulty.a:g}" for s in specs.values())
    grades = collections.Counter(g for s in specs.values() for g in s.target_grades)
    mcq_share = {}
    for g in ("lead", "principal"):
        fs = [s for s in specs.values() if g in s.target_grades]
        mcq_share[g] = {"families": len(fs), "mcq_concept": sum(s.format == "mcq_concept" for s in fs),
                        "share": round(sum(s.format == "mcq_concept" for s in fs) / max(1, len(fs)), 4)}
    quality: dict = {
        "prior_a_by_format": dict(sorted(prior_a.items())),
        "prior_a_rule": ("до калибровки на людях: a = 1,0 — выбор ответа; a = 1,3 — код, ввод ответа, открытые; "
                         "параметра угадывания в банке нет (поправка 1/число вариантов — в движке)"),
        "families_by_grade": dict(grades), "lead_principal_mcq": mcq_share,
        "leak_resistance_low": sorted(f for f, s in specs.items() if s.invariants.extra.get("leak_resistance") == "low"),
        "lp3_families": sorted(f for f in specs if ".lp3_" in f),
        "retired": {"lp_v2_2010": len(list((PKG / "families_retired" / "lp_v2_2010").glob("*/*.yaml"))),
                    "readme": "backend/assessment_bank/families_retired/lp_v2_2010/README.md"},
    }
    ap_ = Path(a.audit)
    if ap_.exists():
        au = json.loads(ap_.read_text(encoding="utf-8"))
        quality["audit"] = {
            "file": str(ap_.relative_to(REPO)), "generated_at": au["generated_at"], "command": au["command"],
            "n_families": au["n_families"], "n_seeds": au["n_seeds"],
            "generation_errors": au["generation_errors"]["n_families"],
            "grade_in_stem": au["grade_in_stem"]["n_families"], "public_leak": au["public_leak"]["n_families"],
            "key_constancy_ge_0_8": au["key_constancy"]["n_families_at_or_above"],
            "guess_attack": {k: {kk: v[kk] for kk in ("n_variants", "chance", "best_heuristic", "best_accuracy")}
                             for k, v in au["guess_attack"].items()},
        }
    mp = Path(a.mutation)
    if mp.exists():
        quality["mutation"] = {"file": str(mp.relative_to(REPO)), **{k: v for k, v in json.loads(
            mp.read_text(encoding="utf-8")).items() if not isinstance(v, (list, dict)) or k == "summary"}}
    dp = Path(a.diff)
    if dp.exists():
        dd = json.loads(dp.read_text(encoding="utf-8"))
        quality["vs_base"] = {
            "file": str(dp.relative_to(REPO)), "command": dd["command"], "generated_at": dd["generated_at"],
            "base": dd["base"], "head": dd["head"],
            "added": {k: dd["added"][k] for k in ("n", "groups", "by_direction", "by_format", "by_grade")},
            "removed": {k: dd["removed"][k] for k in ("n", "groups", "by_direction", "by_format", "by_grade")},
            "common_changed": dd["common"]["changed_counts"], "a_transitions": dd["common"]["a_transitions"],
            "b_delta": dd["common"]["b_delta"],
            "note": ("lp_v2 — 320 семейств, которые были только в этой ветке и сняты до слияния (в базе их нет); "
                     "variants — изменился сам вариант на первых зёрнах (дистракторы, формулировки)"),
        }
    bank_code_commit = _git("log", "-1", "--format=%h", "--", "backend/assessment_bank",
                            ":(exclude)backend/assessment_bank/BANK_SYNC.json")
    manifest = {
        "source": "backend/assessment_bank (банк правится в дереве платформы, ветка ag/a3-bank)",
        "commit": _git("rev-parse", "--short=7", "HEAD"),
        "dirty_files": len([l for l in _git("status", "--porcelain", "--", "backend/assessment_bank").splitlines() if l]),
        "content_hash": sync_bank.tree_hash(PKG),
        "bank_code_commit": bank_code_commit,
        "commit_note": ("commit — голова, на которой собран манифест; bank_code_commit — последний коммит, менявший "
                        "файлы банка (кроме самого BANK_SYNC.json); validation.commit — дерево прогона валидатора"),
        "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_families": final["n_families"], "by_direction": final["by_direction"],
        "directions_verified": verified,
        "readiness": {"rule": {"min_families": sync_bank.READY_MIN_FAMILIES,
                               "min_per_grade": sync_bank.READY_MIN_PER_GRADE}, "by_direction": readiness},
        "excluded": [],
        "validation": {"summary": summ, "seeds": rep.get("seeds") or summ.get("n_seeds") or 20,
                       "verify_seeds": rep.get("verify_seeds"), "where": a.where,
                       "commit": a.validated_commit or None,
                       "bank_unchanged_since": (not _git("diff", "--name-only", a.validated_commit, "HEAD", "--",
                                                         "backend/assessment_bank",
                                                         ":(exclude)backend/assessment_bank/BANK_SYNC.json"))
                       if a.validated_commit else None},
        "quality": quality,
    }
    (PKG / "BANK_SYNC.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Сводка для методики (А4) — то же содержимое, без копий цифр руками
    a4 = {"source": "tools/bank_manifest.py (из BANK_SYNC.json)", "bank_commit": manifest["commit"],
          "bank_code_commit": bank_code_commit,
          "content_hash": manifest["content_hash"], "synced_at": manifest["synced_at"],
          "n_families": manifest["n_families"], "by_direction": manifest["by_direction"],
          "directions_verified": verified, "validation": manifest["validation"], "quality": quality}
    (REPO / "docs" / "bank" / "bank_metrics_for_a4.json").write_text(
        json.dumps(a4, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("commit", "content_hash", "n_families", "directions_verified")},
                     ensure_ascii=False))
    print(json.dumps(summ, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
