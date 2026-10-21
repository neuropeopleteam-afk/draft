"""Единственный прогон на ОТЛОЖЕННОЙ части Djinni по PROTOCOL.md (А17, 21.10.2026).

  python tools/realdata/djinni/final.py freeze   # собрать bench_holdout, записать FREEZE.json (коммит ДО прогона)
  cd backend && python ../tools/realdata/djinni/final.py run   # проверить хэши → обе конфигурации → external_djinni.json

run отказывается работать, если код, протокол, продуктовый код подбора или набор не совпадают с FREEZE.json,
и если external_djinni.json уже существует (один прогон).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
from split import DJINNI_DIR  # noqa: E402

DOCS = ROOT / "docs/realdata/djinni"
FREEZE = DOCS / "FREEZE.json"
OUT = DOCS / "external_djinni.json"
CODE = ["split.py", "build.py", "adapter.py", "metrics.py", "run.py", "final.py"]
PRODUCT_DIRS = ["backend/app/modules/matching", "backend/app/modules/catalog", "backend/app/modules/resume",
                "backend/app/modules/profiles"]
CONFIGS = {
    "B_grade_from_text": {"env": {"MATCH_UNCONFIRMED_BY_CLAIM": "1"},
                          "args": ["--mode", "adapter", "--need-dir", "title", "--need-grade"]},
    "A_direction_only": {"env": {}, "args": ["--mode", "adapter", "--need-dir", "title"]},
}
PRODUCT_FLAGS = ("MATCH_UNCONFIRMED_BY_CLAIM", "CATALOG_EXT_ENABLED", "MATCH_MUST_FIRST", "RANK_CORE_SKILL",
                 "MATCH_MUST_DECLARED", "NEED_TITLE_ROLE")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tree_sha(rel: str) -> str:
    h = hashlib.sha256()
    for p in sorted((ROOT / rel).rglob("*.py")):
        h.update(str(p.relative_to(ROOT)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def fingerprint() -> dict:
    return {"code": {f: sha(HERE / f) for f in CODE}, "protocol_sha256": sha(DOCS / "PROTOCOL.md"),
            "split_manifest_sha256": sha(DOCS / "split_manifest.json"),
            "product": {d: tree_sha(d) for d in PRODUCT_DIRS}}


def bench_path() -> Path:
    return DJINNI_DIR / "bench_holdout.json"


def freeze() -> None:
    from build import build

    b = build("holdout")
    bench_path().write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    n2 = sum(1 for v in b["vacancies"] for x in v["labels"].values() if x == 2)
    n1 = sum(1 for v in b["vacancies"] for x in v["labels"].values() if x == 1)
    out = {"frozen_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "part": "holdout",
           "bench_sha256": b["bench_sha256"], "vacancy_ids_sha256": b["vacancy_ids_sha256"],
           "cv_ids_sha256": b["cv_ids_sha256"], "n_vacancies": len(b["vacancies"]), "label2": n2, "label1": n1,
           "configs": CONFIGS, "main_config": "B_grade_from_text", "main_metric": "ndcg@10", **fingerprint()}
    FREEZE.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("bench_sha256", "n_vacancies", "label2", "label1")}))


def run() -> None:
    fz = json.loads(FREEZE.read_text(encoding="utf-8"))
    fp = fingerprint()
    bad = [k for k in fp if fp[k] != fz[k]]
    assert not bad, f"не совпадает с FREEZE.json: {bad}"
    assert not OUT.exists(), "external_djinni.json уже есть — прогон на отложенной части один"
    from build import build

    b = build("holdout")
    assert b["bench_sha256"] == fz["bench_sha256"], "набор отложенной части не совпадает с FREEZE.json"
    bench_path().write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    res = {}
    for name, cfg in CONFIGS.items():
        env = {k: v for k, v in os.environ.items() if k not in PRODUCT_FLAGS}
        env.update({"LLM_DISABLED": "true", "DJINNI_DIR": str(DJINNI_DIR), **cfg["env"]})
        dst = bench_path().parent / f"holdout_{name}.json"
        subprocess.run([sys.executable, str(HERE / "run.py"), str(bench_path()), str(dst), *cfg["args"]],
                       cwd=ROOT / "backend", env=env, check=True)
        res[name] = json.loads(dst.read_text(encoding="utf-8"))
    main = res[fz["main_config"]]
    lo = main["draft_minus_bm25"][fz["main_metric"]]["ci95"][0]
    out = {
        "artifact": "external_djinni", "agent": "A17", "date": dt.date.today().isoformat(),
        "dataset": "Djinni Recruitment Dataset (lang-uk, MIT), English, holdout 80 %",
        "condition": "внешний открытый набор, метки-посредники (категория и стаж из анкеты), не люди; режим «без теста»; "
                     f"N = {fz['n_vacancies']} вакансий × 200 анкет; один прогон после FREEZE",
        "command": "cd backend && python ../tools/realdata/djinni/final.py run",
        "git_head_at_run": head, "freeze": {k: fz[k] for k in ("frozen_at", "bench_sha256", "vacancy_ids_sha256",
                                                              "cv_ids_sha256", "protocol_sha256")},
        "main_config": fz["main_config"], "main_metric": fz["main_metric"],
        "success_rule": "нижняя граница 95 % ДИ (B − BM25) по nDCG@10 > 0",
        "success": lo > 0,
        "configs": {n: {"flags": r["flags"], "mode": r["mode"], "need_dir": r["need_dir"], "need_grade": r["need_grade"],
                        "adapter": r["adapter"], "seconds": r["seconds"], "summary": r["summary"],
                        "draft_minus_bm25": r["draft_minus_bm25"]} for n, r in res.items()},
        "per_vacancy": {n: [{k: p[k] for k in ("id", "category", "exp_years", "parsed_direction", "parsed_grade",
                                               "uploaded", "eligible", "draft", "bm25")} for p in r["per_vacancy"]]
                        for n, r in res.items()},
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for n, r in res.items():
        print(n, {s: {k: v["mean"] for k, v in r["summary"][s].items()} for s in r["summary"]})
    print("success", out["success"], "B-BM25 ndcg@10", main["draft_minus_bm25"]["ndcg@10"])


if __name__ == "__main__":
    {"freeze": freeze, "run": run}[sys.argv[1]]()
