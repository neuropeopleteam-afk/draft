"""Внешний бенчмарк подбора на открытом наборе Djinni (lang-uk, MIT) — загрузка и разбиение (агент А17, 21.10.2026).

Наборы (Hugging Face, ревизии зафиксированы):
  * lang-uk/recruitment-dataset-job-descriptions-english  — вакансии (141 897);
  * lang-uk/recruitment-dataset-candidate-profiles-english — анкеты кандидатов (210 250).
Статья: Drushchak et al., UNLP 2024, https://aclanthology.org/2024.unlp-1.2/

Разбиение — детерминированное, по хэшу (без случайного генератора и без взгляда на тексты):
    part(id) = "dev", если int(sha256(f"{SEED}:{kind}:{id}")[:8], 16) < DEV_SHARE · 2^32, иначе "holdout".
РАЗРАБОТКА (dev, 20 %) — единственная часть, на которой настраивается адаптер (разбор английских текстов, словарь
навыков, флаги конвейера). ОТЛОЖЕННАЯ (holdout, 80 %) — один прогон после коммита протокола и FREEZE.

Сырьё — вне репозитория (DJINNI_DIR, по умолчанию /home/user/workspace/data/djinni). В репозиторий — манифест:
SHA-256 файлов parquet, правило и сид, число записей и SHA-256 отсортированных списков id каждой части.

  python tools/realdata/djinni/split.py fetch     # скачать parquet нужных ревизий в DJINNI_DIR
  python tools/realdata/djinni/split.py split     # → docs/realdata/djinni/split_manifest.json
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DJINNI_DIR = Path(os.environ.get("DJINNI_DIR", "/home/user/workspace/data/djinni"))
OUT = ROOT / "docs/realdata/djinni/split_manifest.json"
SEED = "a17-djinni-2026-10-21"
DEV_SHARE = 0.20
SOURCES = {
    "jobs": {"repo": "lang-uk/recruitment-dataset-job-descriptions-english",
             "revision": "b56a6054c10f1266a141e37c8df66c79ff2863af", "file": "jobs.parquet"},
    "cvs": {"repo": "lang-uk/recruitment-dataset-candidate-profiles-english",
            "revision": "86255174c6c378a2b52cd7e81d79002c64d899a6", "file": "cvs.parquet"},
}


def part_of(kind: str, rid: str) -> str:
    h = hashlib.sha256(f"{SEED}:{kind}:{rid}".encode()).hexdigest()
    return "dev" if int(h[:8], 16) < DEV_SHARE * 2 ** 32 else "holdout"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_ids(ids) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def load(kind: str):
    import pandas as pd

    return pd.read_parquet(DJINNI_DIR / SOURCES[kind]["file"])


def fetch() -> None:
    DJINNI_DIR.mkdir(parents=True, exist_ok=True)
    for s in SOURCES.values():
        url = f"https://huggingface.co/datasets/{s['repo']}/resolve/{s['revision']}/data/train-00000-of-00001.parquet"
        dst = DJINNI_DIR / s["file"]
        if not dst.exists():
            urllib.request.urlretrieve(url, dst)
        print(s["file"], sha256_file(dst))


def split() -> dict:
    out = {"seed": SEED, "dev_share": DEV_SHARE,
           "rule": 'part = "dev" if int(sha256(f"{seed}:{kind}:{id}")[:8], 16) < dev_share * 2**32 else "holdout"',
           "license": "MIT (lang-uk/recruitment-dataset-*)", "paper": "https://aclanthology.org/2024.unlp-1.2/",
           "sources": {}, "parts": {}}
    for kind, s in SOURCES.items():
        df = load(kind)
        ids = df["id"].astype(str).tolist()
        assert len(ids) == len(set(ids)), f"{kind}: id не уникальны"
        parts = {"dev": [], "holdout": []}
        for rid in ids:
            parts[part_of(kind, rid)].append(rid)
        out["sources"][kind] = {**{k: v for k, v in s.items() if k != "file"},
                                "url": f"https://huggingface.co/datasets/{s['repo']}",
                                "parquet_sha256": sha256_file(DJINNI_DIR / s["file"]), "rows": len(ids)}
        out["parts"][kind] = {p: {"n": len(v), "ids_sha256": sha256_ids(v)} for p, v in parts.items()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out["parts"], indent=1))
    return out


if __name__ == "__main__":
    {"fetch": fetch, "split": split}[sys.argv[1]]()
