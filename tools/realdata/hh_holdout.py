"""Отложенный набор реальных вакансий hh.ru для честной проверки разбора и подбора (21.10.2026).

Зачем. Словарь навыков, синонимы и классификатор направления настраивались на 414 вакансиях корпуса
``docs/realdata/hh_match_corpus.json`` (собран 2026-10-10) — цифры на нём оптимистичны («набор разработки»).
Отложенный набор — свежие вакансии, опубликованные после сбора корпуса разработки, которых в нём нет ни по номеру,
ни по тексту, ни по паре «работодатель + название». Порядок, который нельзя нарушать:

  1. collect — собрать (тот же метод отбора и разметки, что у корпуса разработки: hh_plus.collect);
  2. freeze  — посчитать SHA-256 набора и записать docs/realdata/hh_holdout_FREEZE.json; ЗАКОММИТИТЬ ДО прогона;
  3. run     — один прогон разбора и подбора (hh_plus.match на этом корпусе); повторный запуск запрещён
               (docs/realdata/hh_holdout_RUN.json уже есть) — новый прогон = новый отложенный набор.

Метки — только из структурированных полей hh.ru (роль и слова названия → направление, слово грейда в названии →
грейд, «Ключевые навыки» → теги), разбору не даются. Тексты вакансий в репозиторий не входят (FTT.6): в репозитории —
номера, ссылки, хэши текстов и производные метки; сырьё — HH_CORPUS_DIR вне репозитория.

  set -a; . <файл с HH_APP_TOKEN и HH_USER_AGENT>; set +a      # значения не печатать; токен не перевыпускать
  cd backend
  HH_CORPUS_DIR=<сырьё> python ../tools/realdata/hh_holdout.py collect --per 12 --date-from 2026-10-11
  python ../tools/realdata/hh_holdout.py freeze      # → git commit docs/realdata/hh_holdout_*.json
  DATABASE_URL=sqlite:///<демо-БД> CATALOG_EXT_ENABLED=1 HH_CORPUS_DIR=<сырьё> python ../tools/realdata/hh_holdout.py run
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools/realdata"))

DEV_CORPUS = ROOT / "docs/realdata/hh_match_corpus.json"
HOLDOUT = ROOT / "docs/realdata/hh_holdout_corpus.json"
FREEZE = ROOT / "docs/realdata/hh_holdout_FREEZE.json"
RUN = ROOT / "docs/realdata/hh_holdout_RUN.json"
OUT_JSON = ROOT / "backend/app/modules/validation/data/hh_match_holdout.json"
OUT_MD = ROOT / "docs/realdata/HH_MATCH_HOLDOUT.md"


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", " ", (s or "").casefold()).strip()


def manifest_lines(items: list[dict]) -> list[str]:
    return sorted(f"{it['id']}\t{it['text_sha256']}\t{it['bucket']}" for it in items)


def manifest_sha(items: list[dict]) -> str:
    return hashlib.sha256("\n".join(manifest_lines(items)).encode()).hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def collect(per: int, date_from: str) -> None:
    import hh_plus as hp
    from app.modules.hh.directions import HH_DIRECTIONS, search_params

    dev = json.loads(DEV_CORPUS.read_text(encoding="utf-8"))
    dev_ids = {it["id"] for it in dev["items"]}
    dev_sha = {it["text_sha256"] for it in dev["items"]}
    dev_pairs = set()
    for it in dev["items"]:
        v = hp.detail(None, it["id"])
        if v:
            dev_pairs.add(((v.get("employer") or {}).get("id"), _norm(v.get("name"))))
    cl = hp.client()
    picked: dict[str, tuple[str, str, str]] = {}
    skipped = {"dev_id": 0, "dev_text": 0, "dev_employer_title": 0, "dup_text": 0, "old": 0}
    seen_sha: set[str] = set()

    def take(items: list[dict], d: str, g: str, by: str, have: int) -> int:
        n = 0
        for it in items:
            if have + n >= per:
                break
            vid = it["id"]
            if vid in picked:
                continue
            if vid in dev_ids:
                skipped["dev_id"] += 1
                continue
            if (it.get("published_at") or "")[:10] < date_from:
                skipped["old"] += 1
                continue
            v = hp.detail(cl, vid)
            if v is None:
                continue
            sha = hashlib.sha256(hp.text_of(v).encode()).hexdigest()
            if sha in dev_sha:
                skipped["dev_text"] += 1
                continue
            if ((v.get("employer") or {}).get("id"), _norm(v.get("name"))) in dev_pairs:
                skipped["dev_employer_title"] += 1
                continue
            if sha in seen_sha:
                skipped["dup_text"] += 1
                continue
            seen_sha.add(sha)
            picked[vid] = (d, g, by)
            n += 1
        return n

    for d in HH_DIRECTIONS:
        for g in hp.GRADES:
            n = m = 0
            for page in range(3):
                if n >= per:
                    break
                ps = search_params(d, g, "113", per_page=50) + [("date_from", date_from), ("page", str(page))]
                n += take(hp.search(cl, ps)["data"].get("items") or [], d, g, "name", n)
            for page in range(3):
                if n + m >= per:
                    break
                ps = (search_params(d, None, "113", per_page=50, experience=[hp.TOPUP_EXPERIENCE[g]])
                      + [("date_from", date_from), ("page", str(page))])
                m += take(hp.search(cl, ps)["data"].get("items") or [], d, g, "experience", n + m)
            print(f"{d}.{g}: {n} по названию + {m} по опыту")
    items = []
    for vid, (d, g, by) in picked.items():
        v = hp.detail(None, vid)
        items.append({"id": vid, "url": f"https://hh.ru/vacancy/{vid}", "bucket": f"{d}.{g}",
                      "labels": hp.labels(v, d, g, by), "published_at": v.get("published_at"),
                      "text_sha256": hashlib.sha256(hp.text_of(v).encode()).hexdigest()})
    out = {"schema_version": 1, "kind": "holdout", "collected_at": hp.today(), "date_from": date_from,
           "label_note": hp.LABEL_NOTE,
           "purpose": "Отложенный набор: свежие вакансии hh.ru, которых нет в корпусе разработки (414, 2026-10-10) "
                      "ни по номеру, ни по тексту, ни по паре «работодатель + название». На нём словарь, синонимы и "
                      "классификатор не настраивались; прогон — один (hh_holdout.py run).",
           "method": f"Тот же отбор и та же разметка, что у корпуса разработки (hh_plus.collect): GET /vacancies по 9 "
                     f"направлениям × 4 грейда, роль hh.ru + слова направления и грейда в названии, вся Россия, свежие "
                     f"(date_from={date_from}), до {per} на ячейку, добор — по опыту hh.ru; страницы 0–2.",
           "excluded": skipped, "n": len(items), "items": items}
    HOLDOUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("отложенный набор:", len(items), "исключено:", skipped, "→", HOLDOUT.relative_to(ROOT))


def freeze() -> None:
    if FREEZE.exists():
        sys.exit(f"{FREEZE.relative_to(ROOT)} уже есть — набор заморожен; новый набор = новый файл и новая дата")
    h = json.loads(HOLDOUT.read_text(encoding="utf-8"))
    sha = manifest_sha(h["items"])
    out = {"frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "corpus": str(HOLDOUT.relative_to(ROOT)),
           "n": len(h["items"]), "manifest_sha256": sha,
           "manifest_rule": "SHA-256 строк «id<TAB>text_sha256<TAB>bucket», отсортированных, через \\n",
           "corpus_file_sha256": hashlib.sha256(HOLDOUT.read_bytes()).hexdigest(),
           "code_before_run": git_head(),
           "rule": "Зафиксировано до прогона. Прогон один (hh_holdout.py run); словарь, синонимы, классификатор и "
                   "ранжирование после прогона на этом наборе не настраиваются."}
    FREEZE.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("заморожено:", out["n"], "вакансий, SHA-256", sha)


def run(limit: int) -> None:
    if RUN.exists():
        sys.exit(f"{RUN.relative_to(ROOT)} уже есть — отложенный набор использован; повторный прогон запрещён")
    fz = json.loads(FREEZE.read_text(encoding="utf-8"))
    h = json.loads(HOLDOUT.read_text(encoding="utf-8"))
    sha = manifest_sha(h["items"])
    if sha != fz["manifest_sha256"]:
        sys.exit("набор изменён после заморозки: хэш не совпадает")
    tmp = ROOT / ".holdout_run"
    tmp.mkdir(exist_ok=True)
    env = dict(os.environ, HH_MATCH_CORPUS=str(HOLDOUT), HH_MATCH_OUT=str(tmp))
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    subprocess.check_call([sys.executable, str(ROOT / "tools/realdata/hh_plus.py"), "match", "--limit", str(limit)],
                          env=env, cwd=str(ROOT / "backend"))
    res = json.loads((tmp / "hh_match.json").read_text(encoding="utf-8"))
    res["holdout"] = {"freeze": fz, "manifest_sha256_checked": sha, "run_started_at": started, "code": git_head()}
    OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    md = (tmp / "HH_MATCH.md").read_text(encoding="utf-8").replace(
        "# Подбор на реальных вакансиях hh.ru",
        "# Подбор на реальных вакансиях hh.ru — ОТЛОЖЕННЫЙ набор\n\n"
        f"Набор заморожен {fz['frozen_at']} (SHA-256 `{fz['manifest_sha256']}`, {fz['n']} вакансий, код до прогона "
        f"`{fz['code_before_run'][:9]}`), прогон один — {started}. На этих вакансиях ничего не настраивалось.", 1)
    OUT_MD.write_text(md, encoding="utf-8")
    RUN.write_text(json.dumps({"run_started_at": started, "manifest_sha256": sha, "code": git_head(),
                               "result": str(OUT_JSON.relative_to(ROOT))}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print("прогон записан:", OUT_JSON.relative_to(ROOT), OUT_MD.relative_to(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--per", type=int, default=12)
    c.add_argument("--date-from", default="2026-10-11")
    sub.add_parser("freeze")
    r = sub.add_parser("run")
    r.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()
    {"collect": lambda: collect(a.per, a.date_from), "freeze": freeze, "run": lambda: run(a.limit)}[a.cmd]()


if __name__ == "__main__":
    main()
