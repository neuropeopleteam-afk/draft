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

Второй отложенный набор (21.10 вечер, проверка классификатора направления dir-v2 — флаг NEED_TITLE_ROLE): те же шаги с
``--tag 2`` — свои файлы ``hh_holdout2_*``, ``hh_match_holdout2.json``, ``HH_MATCH_HOLDOUT2.md``; collect исключает и
набор разработки, и первый отложенный набор, страницы поиска 0–5; run в том же прогоне считает контроль — направление с
NEED_TITLE_ROLE=0; adjudicate проверяет спорные метки обоих вариантов (каждую вакансию один раз). Протокол —
``docs/realdata/hh_holdout2_PROTOCOL.md`` (коммит до прогона).

  HH_CORPUS_DIR=<сырьё> python ../tools/realdata/hh_holdout.py --tag 2 collect --per 12 --date-from 2026-10-11
  python ../tools/realdata/hh_holdout.py --tag 2 freeze
  DATABASE_URL=… CATALOG_EXT_ENABLED=1 HH_CORPUS_DIR=<сырьё> HH_MATCH_COMPARE=0 python ../tools/realdata/hh_holdout.py --tag 2 run
  set -a; . .secrets/openrouter.env; set +a; python tools/realdata/hh_holdout.py --tag 2 adjudicate
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
TAG = ""  # "" — первый отложенный набор (21.10 утро); "2" — второй (проверка dir-v2), см. set_tag
# Наборы, которых не должно быть в новом отложенном: разработка + все прежние отложенные (по номеру, тексту и паре
# «работодатель + название»); для первого набора — только разработка
EXCLUDE = [DEV_CORPUS]
PAGES = range(3)
DIR_CONTROL = ""  # флаг разбора, который в том же прогоне считается и выключенным (контроль «до/после»)


def set_tag(tag: str) -> None:
    global TAG, HOLDOUT, FREEZE, RUN, OUT_JSON, OUT_MD, ADJ, PROTOCOL, DISPUTED, EXCLUDE, PAGES, DIR_CONTROL
    TAG = tag
    HOLDOUT = ROOT / f"docs/realdata/hh_holdout{tag}_corpus.json"
    FREEZE = ROOT / f"docs/realdata/hh_holdout{tag}_FREEZE.json"
    RUN = ROOT / f"docs/realdata/hh_holdout{tag}_RUN.json"
    OUT_JSON = ROOT / f"backend/app/modules/validation/data/hh_match_holdout{tag}.json"
    OUT_MD = ROOT / f"docs/realdata/HH_MATCH_HOLDOUT{tag}.md"
    ADJ = ROOT / f"docs/realdata/hh_holdout{tag}_adjudication.json"
    PROTOCOL = ROOT / f"docs/realdata/hh_holdout{tag}_PROTOCOL.md"
    DISPUTED = Path(os.environ.get("HH_HOLDOUT_DISPUTED") or ROOT / f".holdout{tag}_disputed.jsonl")  # вне git
    if tag == "2":
        # второй отложенный набор (21.10 вечер): проверка dir-v2 (NEED_TITLE_ROLE) на вакансиях, которых не было ни в
        # наборе разработки, ни в первом отложенном (после его отчёта на нём настраивался dir-v2)
        EXCLUDE = [DEV_CORPUS, ROOT / "docs/realdata/hh_holdout_corpus.json"]
        PAGES = range(6)
        DIR_CONTROL = "NEED_TITLE_ROLE"


set_tag("")
ARBITERS = ("anthropic/claude-sonnet-5.5", "openai/gpt-6.1-sol")
DIR_CHOICES = ("backend", "frontend", "mobile", "qa", "devops", "data_eng", "data_ml", "analyst", "security", "not_it")
GRADE_CHOICES = ("intern", "junior", "middle", "senior", "none")


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", " ", (s or "").casefold()).strip()


def manifest_lines(items: list[dict]) -> list[str]:
    return sorted(f"{it['id']}\t{it['text_sha256']}\t{it['bucket']}" for it in items)


def manifest_sha(items: list[dict]) -> str:
    return hashlib.sha256("\n".join(manifest_lines(items)).encode()).hexdigest()


def git_head() -> str:
    if os.environ.get("CODE_COMMIT"):  # прогон на копии без .git (сервер «Москва»): коммит передаётся явно
        return os.environ["CODE_COMMIT"]
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def collect(per: int, date_from: str) -> None:
    import hh_plus as hp
    from app.modules.hh.directions import HH_DIRECTIONS, search_params

    if HOLDOUT.exists():
        sys.exit(f"{HOLDOUT.relative_to(ROOT)} уже есть — набор собран; новый набор = новый файл")
    prev_items = [it for p in EXCLUDE for it in json.loads(p.read_text(encoding="utf-8"))["items"]]
    dev_ids = {it["id"] for it in prev_items}
    dev_sha = {it["text_sha256"] for it in prev_items}
    dev_pairs = set()
    for it in prev_items:
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
            for page in PAGES:
                if n >= per:
                    break
                ps = search_params(d, g, "113", per_page=50) + [("date_from", date_from), ("page", str(page))]
                n += take(hp.search(cl, ps)["data"].get("items") or [], d, g, "name", n)
            for page in PAGES:
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
    excl = [str(p.relative_to(ROOT)) for p in EXCLUDE]
    out = {"schema_version": 1, "kind": f"holdout{TAG}", "collected_at": hp.today(), "date_from": date_from,
           "label_note": hp.LABEL_NOTE,
           "purpose": ("Отложенный набор: свежие вакансии hh.ru, которых нет в корпусе разработки (414, 2026-10-10) "
                       "ни по номеру, ни по тексту, ни по паре «работодатель + название». На нём словарь, синонимы и "
                       "классификатор не настраивались; прогон — один (hh_holdout.py run).") if not TAG else
                      ("Второй отложенный набор (проверка классификатора направления dir-v2): свежие вакансии hh.ru, "
                       "которых нет ни в корпусе разработки (414), ни в первом отложенном наборе (381; после его отчёта "
                       "на нём настраивался dir-v2) — ни по номеру, ни по тексту, ни по паре «работодатель + название». "
                       "Прогон — один (hh_holdout.py --tag 2 run)."),
           "method": f"Тот же отбор и та же разметка, что у корпуса разработки (hh_plus.collect): GET /vacancies по 9 "
                     f"направлениям × 4 грейда, роль hh.ru + слова направления и грейда в названии, вся Россия, свежие "
                     f"(date_from={date_from}), до {per} на ячейку, добор — по опыту hh.ru; страницы "
                     f"{PAGES.start}–{PAGES.stop - 1}.",
           "excluded_sets": excl, "excluded": skipped, "n": len(items), "items": items}
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
           **({"protocol": str(PROTOCOL.relative_to(ROOT)),
               "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()} if TAG and PROTOCOL.exists() else {}),
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
    tmp = ROOT / f".holdout{TAG}_run"
    tmp.mkdir(exist_ok=True)
    env = dict(os.environ, HH_MATCH_CORPUS=str(HOLDOUT), HH_MATCH_OUT=str(tmp))
    if DIR_CONTROL:
        env["HH_MATCH_DIR_CONTROL"] = DIR_CONTROL
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    subprocess.check_call([sys.executable, str(ROOT / "tools/realdata/hh_plus.py"), "match", "--limit", str(limit)],
                          env=env, cwd=str(ROOT / "backend"))
    res = json.loads((tmp / "hh_match.json").read_text(encoding="utf-8"))
    # тексты спорных вакансий — для арбитража (adjudicate); файл вне git (FTT.6: тексты hh.ru в репозиторий не входят)
    import hh_plus as hp
    with DISPUTED.open("w", encoding="utf-8") as fh:
        for e in _disputed_all(res):
            v = hp.detail(None, e["id"])
            if v:
                fh.write(json.dumps({"id": e["id"], "field": e["field"], "title": v.get("name") or "",
                                     "text": hp.text_of(v)[:3000]}, ensure_ascii=False) + "\n")
    res["holdout"] = {"freeze": fz, "manifest_sha256_checked": sha, "run_started_at": started, "code": git_head()}
    OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    md = (tmp / "HH_MATCH.md").read_text(encoding="utf-8").replace(
        "# Подбор на реальных вакансиях hh.ru",
        f"# Подбор на реальных вакансиях hh.ru — ОТЛОЖЕННЫЙ набор{(' №' + TAG) if TAG else ''}\n\n"
        f"Набор заморожен {fz['frozen_at']} (SHA-256 `{fz['manifest_sha256']}`, {fz['n']} вакансий, код до прогона "
        f"`{fz['code_before_run'][:9]}`), прогон один — {started}. На этих вакансиях ничего не настраивалось.", 1)
    OUT_MD.write_text(md, encoding="utf-8")
    RUN.write_text(json.dumps({"run_started_at": started, "manifest_sha256": sha, "code": git_head(),
                               "result": str(OUT_JSON.relative_to(ROOT))}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print("прогон записан:", OUT_JSON.relative_to(ROOT), OUT_MD.relative_to(ROOT))


ADJ_PROMPT_DIR = (
    "Определи направление IT-вакансии по её названию и тексту. Ответь ОДНИМ словом из списка: "
    "backend (серверная разработка), frontend (веб-интерфейсы), mobile (iOS/Android), qa (тестирование), devops "
    "(инфраструктура, CI/CD, SRE), data_eng (инженер данных, ETL, хранилища), data_ml (data science, машинное обучение), "
    "analyst (системный/бизнес-аналитик, аналитик данных), security (информационная безопасность), not_it (не IT-вакансия). "
    "Только слово, без пояснений.")
ADJ_PROMPT_GRADE = (
    "Определи грейд, который работодатель указал для вакансии (по названию и тексту). Ответь ОДНИМ словом из списка: "
    "intern (стажёр), junior, middle, senior (сюда же lead, тимлид, ведущий, старший), none (грейд не указан). "
    "Только слово, без пояснений.")


def _ask(model: str, prompt: str, title: str, text: str, choices: tuple) -> str | None:
    import urllib.request

    key = os.environ["OPENROUTER_API_KEY"]
    base = os.environ.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1"
    body = {"model": model, "temperature": 0, "max_tokens": 400,
            "messages": [{"role": "system", "content": prompt},
                         {"role": "user", "content": f"Название: {title}\n\nТекст:\n{text}"}]}
    for attempt in range(3):
        try:
            req = urllib.request.Request(f"{base}/chat/completions", data=json.dumps(body).encode(),
                                         headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                out = json.loads(r.read())["choices"][0]["message"]["content"] or ""
            w = re.findall(r"[a-z_]+", out.strip().lower())
            for t in reversed(w):
                if t in choices:
                    return t
            return None
        except Exception:  # noqa: BLE001 — сеть: повтор
            import time

            time.sleep(3 * (attempt + 1))
    return None


def _disputed_all(res: dict) -> list[dict]:
    """Спорные метки основного разбора и (если есть) контрольного — каждая пара (номер, поле) один раз."""
    seen, out = set(), []
    for e in (res.get("disputed") or []) + ((res.get("direction_control") or {}).get("disputed") or []):
        if (e["id"], e["field"]) not in seen:
            seen.add((e["id"], e["field"]))
            out.append(e)
    return out


def adjudicate() -> None:
    if ADJ.exists():
        sys.exit("арбитраж уже выполнен — повтор запрещён (протокол, п. 3)")
    if not RUN.exists():
        sys.exit("сначала один прогон: hh_holdout.py run")
    res = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    texts = {(d["id"], d["field"]): d for d in map(json.loads, DISPUTED.read_text(encoding="utf-8").splitlines())}
    main_ans = {(e["id"], e["field"]): e["actual"] for e in res.get("disputed") or []}
    ctrl = res.get("direction_control") or {}
    ctrl_ans = {(e["id"], e["field"]): e["actual"] for e in ctrl.get("disputed") or []}
    rows = []
    for e in _disputed_all(res):
        key = (e["id"], e["field"])
        t = texts.get(key)
        base = {"id": e["id"], "field": e["field"], "hh_label": e["expected"]}
        if key in main_ans:
            base["parser"] = main_ans[key]
        if key in ctrl_ans:
            base["parser_control"] = ctrl_ans[key]
        if not t:
            rows.append({**base, "arbiters": {}, "final": e["expected"], "why": "нет текста — остаётся метка hh.ru"})
            continue
        prompt, ch = (ADJ_PROMPT_DIR, DIR_CHOICES) if e["field"] == "direction" else (ADJ_PROMPT_GRADE, GRADE_CHOICES)
        ans = {m: _ask(m, prompt, t["title"], t["text"], ch) for m in ARBITERS}
        a = list(ans.values())
        agree = a[0] is not None and a[0] == a[1]
        final = a[0] if agree else e["expected"]
        rows.append({**base, "arbiters": ans, "final": final,
                     "why": "оба арбитра согласны" if agree else "арбитры разошлись — остаётся метка hh.ru"})
        print(e["id"], e["field"], e["expected"], base.get("parser"), base.get("parser_control"), ans, "→", final,
              flush=True)
    ov = res["overall"]

    def after(field: str, base: dict, pkey: str = "parser") -> dict:
        rs = [r for r in rows if r["field"] == field and pkey in r]
        fixed = sum(1 for r in rs if r["final"] == r.get(pkey))
        noisy = sum(1 for r in rs if r["final"] != r.get("hh_label", r["final"]))
        k = base["k"] + fixed
        return {"value": round(k / base["n"], 4) if base["n"] else None, "k": k, "n": base["n"],
                "disputed": len(rs), "parser_right": fixed, "noisy_labels": noisy,
                "noisy_share": round(noisy / base["n"], 4) if base["n"] else None}

    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "protocol": str(PROTOCOL.relative_to(ROOT)),
           "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(), "arbiters": list(ARBITERS),
           "direction": after("direction", ov["direction_ok"]), "grade": after("grade", ov["grade_ok"]),
           "rows": rows,
           "what": "Спорные метки (разбор ≠ метка hh.ru) независимо проверены двумя моделями разных компаний, не видевшими "
                   "ни метку, ни ответ разбора; итог — только при согласии обоих, иначе метка hh.ru. Модели, не люди."}
    if ctrl:
        out["direction_control"] = {**after("direction", ctrl["direction_ok"], "parser_control"), "flag": ctrl["flag"]}
    ADJ.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("направление после проверки:", out["direction"], "грейд:", out["grade"],
          "контроль:", out.get("direction_control"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="", choices=("", "2"), help="«2» — второй отложенный набор (проверка dir-v2)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--per", type=int, default=12)
    c.add_argument("--date-from", default="2026-10-11")
    sub.add_parser("freeze")
    r = sub.add_parser("run")
    r.add_argument("--limit", type=int, default=10)
    sub.add_parser("adjudicate")
    a = ap.parse_args()
    set_tag(a.tag)
    {"collect": lambda: collect(a.per, a.date_from), "freeze": freeze, "run": lambda: run(a.limit),
     "adjudicate": adjudicate}[a.cmd]()


if __name__ == "__main__":
    main()
