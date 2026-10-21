"""Набор hh.ru №2 — слепая проверка СОВПАДЕНИЙ разбора и метки hh.ru и честная проверка грейда (поправка А15).

Протокол — docs/realdata/hh_holdout2_AGREE_PROTOCOL.md (коммит и FREEZE — до проверки). Один запуск:

  cd backend && python ../tools/realdata/hh_agree.py --tag 2 freeze      # до проверки; затем git commit
  set -a; . <ключ OpenRouter>; set +a
  HH_CORPUS_DIR=<сырые карточки> python ../tools/realdata/hh_agree.py --tag 2 run

Тексты вакансий hh.ru в репозиторий не входят (FTT.6): читаются из кэша сырых карточек (HH_CORPUS_DIR), в итог
попадают только номера, ответы арбитров и метрики.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "realdata"))

N_AGREE = 80
N_GRADE = 120
# протокол: noExperience → intern/junior, between1And3 → junior/middle, between3And6 → middle/senior, moreThan6 → senior
EXPERIENCE_OK = {"noExperience": {"intern", "junior"}, "between1And3": {"junior", "middle"},
                 "between3And6": {"middle", "senior"}, "moreThan6": {"senior"}}
GRADE_STEP = {"intern": 0, "junior": 1, "middle": 2, "senior": 3}


def paths(tag: str) -> dict[str, Path]:
    rd = ROOT / "docs/realdata"
    return {"corpus": rd / f"hh_holdout{tag}_corpus.json", "freeze": rd / f"hh_holdout{tag}_FREEZE.json",
            "run": rd / f"hh_holdout{tag}_RUN.json", "adj": rd / f"hh_holdout{tag}_adjudication.json",
            "protocol": rd / f"hh_holdout{tag}_AGREE_PROTOCOL.md", "agree_freeze": rd / f"hh_holdout{tag}_AGREE_FREEZE.json",
            "out": rd / f"hh_holdout{tag}_agree.json"}


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def wilson(k: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def share(k: float, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": round(k, 2) if isinstance(k, float) else k, "n": n, "share": round(k / n, 4) if n else None,
            "ci95": [round(lo, 4), round(hi, 4)]}


def git_head() -> str:
    if os.environ.get("CODE_COMMIT"):
        return os.environ["CODE_COMMIT"]
    import subprocess

    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def seed_of(tag: str) -> int:
    fz = json.loads(paths(tag)["freeze"].read_text(encoding="utf-8"))
    return int(fz["manifest_sha256"][:8], 16)


def freeze(tag: str) -> None:
    p = paths(tag)
    if p["agree_freeze"].exists():
        sys.exit("уже заморожено")
    if not p["run"].exists():
        sys.exit("нет прогона набора — проверка совпадений идёт после него")
    p["agree_freeze"].write_text(json.dumps({
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "protocol": str(p["protocol"].relative_to(ROOT)), "protocol_sha256": sha_file(p["protocol"]),
        "tool_sha256": sha_file(Path(__file__)), "code_before_check": git_head(), "seed": seed_of(tag),
        "n_agree": N_AGREE, "n_grade_max": N_GRADE,
        "rule": "Зафиксировано до проверки; проверка одна; на этом наборе после неё ничего не настраивается."},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("заморожено:", p["agree_freeze"].relative_to(ROOT))


def _labelled(corpus: dict, res: dict) -> list[dict]:
    dirs = set(res.get("catalog_directions") or [])
    return [it for it in corpus["items"] if it["labels"]["direction"] in dirs]


def run(tag: str) -> None:
    import numpy as np

    import hh_holdout as hd
    import hh_plus as hp
    from app.modules.matching import need_parser

    p = paths(tag)
    if p["out"].exists():
        sys.exit(f"{p['out'].relative_to(ROOT)} уже есть — проверка одна")
    afz = json.loads(p["agree_freeze"].read_text(encoding="utf-8"))
    if afz["protocol_sha256"] != sha_file(p["protocol"]):
        sys.exit("протокол изменён после заморозки")
    corpus = json.loads(p["corpus"].read_text(encoding="utf-8"))
    run_meta = json.loads(p["run"].read_text(encoding="utf-8"))
    res = json.loads((ROOT / run_meta["result"]).read_text(encoding="utf-8"))
    adj = json.loads(p["adj"].read_text(encoding="utf-8")) if p["adj"].exists() else None
    items = _labelled(corpus, res)
    present = {it["id"]: v for it in items if (v := hp.detail(None, it["id"])) is not None}
    items = [it for it in items if it["id"] in present]
    disputed_dir = {e["id"] for e in res.get("disputed") or [] if e["field"] == "direction"}
    agree_ids = sorted(it["id"] for it in items if it["id"] not in disputed_dir)
    by_id = {it["id"]: it for it in items}
    rng = np.random.default_rng(afz["seed"])
    sample = [str(x) for x in rng.choice(agree_ids, size=min(N_AGREE, len(agree_ids)), replace=False)]

    def ask_all(prompt: str, v: dict, choices: tuple) -> dict:
        return {m: hd._ask(m, prompt, v.get("name") or "", hp.text_of(v)[:3000], choices) for m in hd.ARBITERS}

    # A. совпадения
    rows_a, both_wrong, unresolved = [], 0, 0
    for vid in sample:
        lab = by_id[vid]["labels"]["direction"]
        ans = ask_all(hd.ADJ_PROMPT_DIR, present[vid], hd.DIR_CHOICES)
        a = list(ans.values())
        agree = a[0] is not None and a[0] == a[1]
        verdict = ("ok" if agree and a[0] == lab else "both_wrong" if agree else "unresolved")
        both_wrong += verdict == "both_wrong"
        unresolved += verdict == "unresolved"
        rows_a.append({"id": vid, "label_and_parser": lab, "arbiters": ans, "verdict": verdict})
        print("A", vid, lab, ans, verdict, flush=True)
    n_lab = len(items)
    n_agree = len(agree_ids)
    parser_right = 0
    if adj:
        parser_right = sum(1 for r in adj.get("rows") or [] if r.get("field") == "direction"
                           and r.get("final") == r.get("parser") and r.get("final") != r.get("hh_label"))
    ns = len(sample)
    r = both_wrong / ns if ns else 0.0
    r_lo, r_hi = wilson(both_wrong, ns)
    r_worst = (both_wrong + unresolved) / ns if ns else 0.0

    def k_adj(rate: float) -> float:
        return n_agree * (1 - rate) + parser_right

    raw_k = n_agree
    part_a = {
        "what": "Слепая проверка случайных совпадений разбора и метки hh.ru двумя моделями (не люди)",
        "n_labelled": n_lab, "n_agree": n_agree, "n_disputed": len(disputed_dir & set(by_id)),
        "sample": ns, "seed": afz["seed"], "both_wrong": both_wrong, "unresolved": unresolved,
        "both_wrong_share": share(both_wrong, ns),
        "raw": share(raw_k, n_lab),
        "parser_right_in_disputes": parser_right,
        "adjusted": {"share": round(k_adj(r) / n_lab, 4),
                     "ci95": [round(k_adj(r_hi) / n_lab, 4), round(k_adj(r_lo) / n_lab, 4)],
                     "k": round(k_adj(r), 1), "n": n_lab},
        "worst_case": {"share": round(k_adj(r_worst) / n_lab, 4), "note": "«не решено» засчитано как «оба неверны»"},
        "rows": rows_a,
    }
    # B. без роли в названии (правило dir-v2 не сработало)
    no_role = [it for it in items if need_parser.title_role_direction(present[it["id"]].get("name") or "") is None]
    nr_ok = sum(1 for it in no_role if it["id"] not in disputed_dir)
    nr_fixed = 0
    if adj:
        nr_ids = {it["id"] for it in no_role}
        nr_fixed = sum(1 for r_ in adj.get("rows") or [] if r_.get("field") == "direction" and r_.get("id") in nr_ids
                       and r_.get("final") == r_.get("parser") and r_.get("final") != r_.get("hh_label"))
    part_b = {"what": "Вакансии без роли в названии (правило dir-v2 не сработало, разбор — по тексту)",
              "n": len(no_role), "raw": share(nr_ok, len(no_role)),
              "after_disputes": share(nr_ok + nr_fixed, len(no_role))}
    # C. грейд без слова в названии
    no_gw = sorted(it["id"] for it in items if not it["labels"].get("grade_title"))
    if len(no_gw) > N_GRADE:
        no_gw = [str(x) for x in rng.choice(no_gw, size=N_GRADE, replace=False)]
    rows_c = []
    for vid in no_gw:
        v = present[vid]
        pg = need_parser.parse_need(hp.text_of(v), use_llm=False).get("grade")
        ans = ask_all(hd.ADJ_PROMPT_GRADE, v, hd.GRADE_CHOICES)
        a = list(ans.values())
        ref = a[0] if (a[0] is not None and a[0] == a[1] and a[0] != "none") else None
        exp = by_id[vid]["labels"].get("experience")
        rows_c.append({"id": vid, "parser": pg, "arbiters": ans, "reference": ref, "experience": exp})
        print("C", vid, pg, ans, exp, flush=True)
    with_ref = [x for x in rows_c if x["reference"]]
    exact = sum(1 for x in with_ref if x["parser"] == x["reference"])
    pm1 = sum(1 for x in with_ref if x["parser"] in GRADE_STEP
              and abs(GRADE_STEP[x["parser"]] - GRADE_STEP[x["reference"]]) <= 1)
    with_exp = [x for x in rows_c if x["experience"] in EXPERIENCE_OK and x["parser"]]
    part_c = {"what": "Грейд на вакансиях без слова грейда в названии: разбор против слепой разметки двух моделей",
              "n_no_grade_word": len([it for it in items if not it["labels"].get("grade_title")]),
              "checked": len(rows_c), "with_reference": len(with_ref),
              "exact": share(exact, len(with_ref)), "within_one_step": share(pm1, len(with_ref)),
              "parser_no_grade": share(sum(1 for x in rows_c if not x["parser"]), len(rows_c)),
              "experience_concordance": share(sum(1 for x in with_exp if x["parser"] in EXPERIENCE_OK[x["experience"]]),
                                              len(with_exp)),
              "rows": rows_c}
    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "freeze": afz,
           "run": run_meta, "arbiters": list(hd.ARBITERS), "code": git_head(),
           "direction_agreements": part_a, "no_role_in_title": part_b, "grade_without_title_word": part_c,
           "label": "модели, не люди",
           "recompute": "cd backend && python ../tools/realdata/hh_agree.py --tag 2 run (один раз; повтор запрещён)"}
    p["out"].write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("записано:", p["out"].relative_to(ROOT))
    print(json.dumps({k: v for k, v in part_a.items() if k != "rows"}, ensure_ascii=False))
    print(json.dumps(part_b, ensure_ascii=False))
    print(json.dumps({k: v for k, v in part_c.items() if k != "rows"}, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="2")
    ap.add_argument("cmd", choices=["freeze", "run"])
    a = ap.parse_args()
    import hh_holdout as hd

    hd.set_tag(a.tag)
    {"freeze": freeze, "run": run}[a.cmd](a.tag)


if __name__ == "__main__":
    main()
