"""Сравнение банка ветки с базовым банком (А3, 21.10.2026).

Зачем: симуляция А4 шла на банке из BANK_SYNC.json базы (commit 603474f, 1 504 семейства — это содержимое
``backend/assessment_bank`` в ветке integ/2010n). Чтобы было видно, к какому банку относятся цифры, этот скрипт
сравнивает два дерева и пишет JSON: какие семейства добавлены/сняты (по направлениям, форматам, грейдам),
у каких изменились a, b, грейды, время, формат, и у каких на зёрнах 1..N поменялся сам вариант (fingerprint).
Ничего руками: все числа — из загрузки спецификаций и генерации обоих деревьев.

Запуск из корня репозитория:
    python3 tools/bank_diff_base.py --base-ref srv/integ/2010n --seeds 2 --out docs/bank/bank_diff_vs_603474f.json
"""
from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

DUMP = r"""
import json, sys
from assessment_bank.registry import load_specs, generate
seeds = int(sys.argv[1])
out = {}
for fid, s in sorted(load_specs().items()):
    fps = []
    for seed in range(1, seeds + 1):
        try:
            fps.append(generate(fid, seed).fingerprint())
        except Exception as e:  # noqa: BLE001
            fps.append("ERR:" + type(e).__name__)
    out[fid] = {"direction": s.direction, "format": s.format, "grades": list(s.target_grades),
                "a": s.prior_difficulty.a, "b": s.prior_difficulty.b, "time_limit_s": s.time_limit_s,
                "basis": s.prior_difficulty.basis, "generator": s.generator, "fp": fps}
print(json.dumps(out, ensure_ascii=False))
"""


def _git(*a: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True, check=True).stdout.strip()


def _dump(backend: Path, seeds: int) -> dict:
    r = subprocess.run([sys.executable, "-c", DUMP, str(seeds)], cwd=str(backend), capture_output=True, text=True,
                       env={"PYTHONPATH": str(backend), "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/tmp"})
    if r.returncode != 0:
        raise SystemExit(r.stderr[-3000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def _cnt(items, key) -> dict:
    return dict(sorted(collections.Counter(key(x) for x in items).items()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-ref", default="srv/integ/2010n")
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--out", default=str(REPO / "docs" / "bank" / "bank_diff_vs_603474f.json"))
    a = ap.parse_args()

    base_sync = json.loads(_git("show", f"{a.base_ref}:backend/assessment_bank/BANK_SYNC.json"))
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(f"git -C {REPO} archive {a.base_ref} backend/assessment_bank | tar -x -C {td}",
                       shell=True, check=True)
        base = _dump(Path(td) / "backend", a.seeds)
    head = _dump(REPO / "backend", a.seeds)

    added = sorted(set(head) - set(base))
    removed = sorted(set(base) - set(head))
    common = sorted(set(head) & set(base))
    ch = collections.defaultdict(list)
    for f in common:
        x, y = base[f], head[f]
        for k in ("a", "b", "time_limit_s", "format", "direction"):
            if x[k] != y[k]:
                ch[k].append(f)
        if sorted(x["grades"]) != sorted(y["grades"]):
            ch["grades"].append(f)
        if x["basis"] != y["basis"]:
            ch["basis"].append(f)
        if x["fp"] != y["fp"]:
            ch["variants"].append(f)
    a_trans = collections.Counter(f"{base[f]['a']:g}->{head[f]['a']:g}" for f in ch["a"])
    b_delta = [round(head[f]["b"] - base[f]["b"], 3) for f in ch["b"]]
    grade_trans = collections.Counter(f"{'/'.join(base[f]['grades'])}->{'/'.join(head[f]['grades'])}"
                                      for f in ch["grades"])
    rm_items = [base[f] | {"id": f} for f in removed]
    add_items = [head[f] | {"id": f} for f in added]

    def grp(ids):
        return {"lp_v2": sum(".lead_v2." in i or ".principal_v2." in i for i in ids),
                "lp3": sum(".lp3_" in i for i in ids),
                "other": sum(not (".lead_v2." in i or ".principal_v2." in i or ".lp3_" in i) for i in ids)}

    res = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": f"python3 tools/bank_diff_base.py --base-ref {a.base_ref} --seeds {a.seeds}",
        "base": {"ref": a.base_ref, "ref_commit": _git("rev-parse", "--short=9", a.base_ref),
                 "bank_manifest_commit": base_sync.get("commit"), "content_hash": base_sync.get("content_hash"),
                 "n_families_manifest": base_sync.get("n_families"), "n_families_loaded": len(base)},
        "head": {"commit": _git("rev-parse", "--short=9", "HEAD"),
                 "bank_tree": _git("rev-parse", "--short=12", "HEAD:backend/assessment_bank"),
                 "n_families_loaded": len(head)},
        "added": {"n": len(added), "groups": grp(added), "by_direction": _cnt(add_items, lambda x: x["direction"]),
                  "by_format": _cnt(add_items, lambda x: x["format"]),
                  "by_grade": _cnt([g for x in add_items for g in x["grades"]], lambda g: g), "ids": added},
        "removed": {"n": len(removed), "groups": grp(removed), "by_direction": _cnt(rm_items, lambda x: x["direction"]),
                    "by_format": _cnt(rm_items, lambda x: x["format"]),
                    "by_grade": _cnt([g for x in rm_items for g in x["grades"]], lambda g: g), "ids": removed},
        "common": {"n": len(common),
                   "changed_counts": {k: len(v) for k, v in sorted(ch.items())},
                   "a_transitions": dict(sorted(a_trans.items())),
                   "b_delta": {"n": len(b_delta), "min": min(b_delta, default=None), "max": max(b_delta, default=None),
                               "mean": round(sum(b_delta) / len(b_delta), 3) if b_delta else None},
                   "grade_transitions_top": dict(grade_trans.most_common(25)),
                   "variants_changed_note": f"fingerprint варианта на зёрнах 1..{a.seeds} отличается",
                   "ids": {k: v for k, v in sorted(ch.items())}},
        "base_prior_a": _cnt(base.values(), lambda x: f"{x['format']}:{x['a']:g}"),
        "head_prior_a": _cnt(head.values(), lambda x: f"{x['format']}:{x['a']:g}"),
    }
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("base", "head")}, ensure_ascii=False))
    print("added", res["added"]["n"], res["added"]["groups"], "removed", res["removed"]["n"], res["removed"]["groups"])
    print("changed", res["common"]["changed_counts"], "a:", res["common"]["a_transitions"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
