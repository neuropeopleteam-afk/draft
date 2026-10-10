"""Я12 п.4: корпус реальных ИТ-вакансий hh.ru для проверки разбора потребности (FTT.6: парсинг — только для тестовых
данных, не продуктовая механика).

Методика — как у замера Я11 на 50 вакансиях (tools/realdata/parse_compare.py: поля FIELDS, путь правил
``need_parser.parse_need(use_llm=False)``, сравнение с парсером другой ревизии ``--rev``), корпус шире: 150–200
вакансий по ролям каталога (5 направлений × 4 грейда) и отдельные выборки с отрицаниями («опыт не требуется»,
«удалёнка не предусмотрена»). Метки — НЕ из текста, который читает парсер, а из структурированных полей, которые
работодатель заполнил на hh.ru: профессиональная роль, опыт, формат работы, key_skills (→ теги стека справочника).
Парсер видит только название и описание (key_skills ему не даём — это метка навыков).

В репозиторий — только номера, ссылки и наши производные метки (``docs/realdata/hh_corpus.json``), без текстов
вакансий; тексты — в локальном кэше вне репозитория (``HH_CORPUS_DIR``), повтор — с токеном приложения (вакансии в
архиве или удалённые считаются отдельно). Итог — ``docs/validation/HH_PARSE.md`` и
``backend/app/modules/validation/data/hh_parse.json`` (блок на /validation) с датой и SHA кода.

  set -a; . <файл с HH_APP_TOKEN и HH_USER_AGENT>; set +a
  cd backend && python ../tools/realdata/hh_corpus.py collect            # ~4 мин: 1 запрос/с
  cd backend && python ../tools/realdata/hh_corpus.py run [--rev fix/sup3]
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.integrations.vacancies.ats_import import html_to_text  # noqa: E402
from app.modules.catalog.dictionary import find_stack  # noqa: E402
from app.modules.catalog.seed_data import STACK  # noqa: E402
from app.modules.hh.client import HhClient, HhError  # noqa: E402
from app.modules.hh.market import GRADE_WORDS, ROLE_QUERY, _q  # noqa: E402
from app.modules.matching import need_parser  # noqa: E402

CORPUS = ROOT / "docs/realdata/hh_corpus.json"
OUT_JSON = ROOT / "backend/app/modules/validation/data/hh_parse.json"
OUT_MD = ROOT / "docs/validation/HH_PARSE.md"
CACHE = Path(os.environ.get("HH_CORPUS_DIR", "/home/user/workspace/spectrek/data_local/hh_corpus"))
GRADES = ["intern", "junior", "middle", "senior"]
EXP_RANGE = {"noExperience": (0, 0), "between1And3": (1, 3), "between3And6": (3, 6), "moreThan6": (6, 99)}
FORMAT = {"REMOTE": "remote", "ON_SITE": "office", "HYBRID": "hybrid"}
ROLE_DIR = {"124": "qa", "116": "security", "165": "data_ml"}
FRONT = re.compile(r"front|фронт|react|vue|angular|верстальщик", re.I)
BACK = re.compile(r"back|бэк|бек|python|java(?!script)|golang|\bgo\b|php|c#|\.net|kotlin|scala|ruby|c\+\+|node", re.I)
DATA = re.compile(r"data|\bml\b|machine learning|дата|машинн|nlp|computer vision|\bllm\b|\bai\b", re.I)
FULL = re.compile(r"full[\s-]?stack|фулл?стек", re.I)
GRADE_RX = [("intern", re.compile(r"стаж[её]р|intern|trainee|стажировк", re.I)),
            ("junior", re.compile(r"junior|джун|младш", re.I)),
            ("middle", re.compile(r"middle|мидл", re.I)),
            ("senior", re.compile(r"senior|сеньор|синьор|старш|ведущ|\blead\b|тимлид|team ?lead", re.I))]
# Отрицания в тексте (метка «в тексте есть отрицание», по ней проверяем разбор). «Обязательное посещение офиса для
# городов, где есть офис» — не отрицание удалёнки (для остальных — удалённо), такие фразы не берём.
_REM = r"(?:удал[её]нн\w*|удал[её]нк\w*)"
NEG_EXP = re.compile(r"опыт\w*(?:\s+[а-яё]+){0,3}\s+не\s+(?:требуется|обязател|нужен|важен)|без\s+опыта", re.I)
NEG_REMOTE = re.compile(
    _REM + r"(?:\s+(?:и|или)\s+гибридн\w*)?(?:\s+(?:работ\w*|формат\w*))*\s+не\s+(?:предусмотрен|рассматрива|возможн)|"
    + _REM + r"[^.!\n]{0,40}не\s+рассматрива|не\s+рассматрива\w*[^.!\n]{0,25}удал[её]н|"
    r"(?:только|исключительно|строго)\s+(?:в\s+)?офис|без\s+удал[её]нк", re.I)
# Выборки с отрицаниями: фраза ищется только в описании (search_field=description), иначе hh.ru находит «Не требуется»
# в поле опыта, а не в тексте
NEG_QUERIES = [("neg_exp", '"опыт не требуется"', ["96", "124", "165", "116"]),
               ("neg_exp", '"без опыта"', ["96", "124", "165", "116"]),
               ("neg_exp", '"опыт работы не обязателен"', ["96", "124", "165", "116"]),
               ("neg_remote", '"удаленная работа не предусмотрена"', ["96", "124", "165", "116"]),
               ("neg_remote", '"только офис"', ["96", "124", "165", "116"]),
               ("neg_remote", '"удаленку не рассматриваем"', ["96", "124", "165", "116"])]
FIELDS = ["direction", "grade", "experience_years_min", "work_format"]


def client() -> HhClient:
    s = Settings(hh_enabled=True, hh_cache_dir=str(CACHE / "http"), hh_stub=False)
    if not (s.hh_app_token and s.hh_user_agent):
        sys.exit("нужны HH_APP_TOKEN и HH_USER_AGENT в окружении (файл секретов; значения не печатать)")
    return HhClient(s, min_interval_s=1.1)


def code_commit() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


# ------------------------------------------------------------------ метки из структурированных полей hh.ru
def title_grade(title: str) -> tuple[str | None, list[str]]:
    found = [g for g, rx in GRADE_RX if rx.search(title)]
    if not found:
        return None, []
    return found[-1] if len(found) > 1 else found[0], found


def labels(v: dict, bucket: str) -> dict:
    title = v.get("name") or ""
    roles = [r.get("id") for r in v.get("professional_roles") or []]
    direction, acc = None, []
    for r in roles:
        if r in ROLE_DIR:
            direction = ROLE_DIR[r]
    if direction is None and "96" in roles:
        if FULL.search(title):
            direction, acc = "backend", ["backend", "frontend"]
        elif DATA.search(title) and not FRONT.search(title):
            direction = "data_ml"
        elif FRONT.search(title) and not BACK.search(title):
            direction = "frontend"
        elif BACK.search(title):
            direction = "backend"
        elif "." in bucket:
            direction = bucket.split(".")[0]
    g, gs = title_grade(title)
    fmts = sorted({FORMAT[x["id"]] for x in v.get("work_format") or [] if x.get("id") in FORMAT})
    exp = (v.get("experience") or {}).get("id")
    ks = [s.get("name", "") for s in v.get("key_skills") or []]
    ks_tags = sorted({t for s in ks for t in find_stack(s) if t in STACK})
    text = html_to_text(v.get("description"))
    sal = v.get("salary_range") or v.get("salary") or {}
    return {"direction": direction, "direction_acceptable": acc or ([direction] if direction else []),
            "grade": g, "grade_acceptable": gs, "experience": exp, "work_formats": fmts, "key_skills_tags": ks_tags,
            "n_key_skills": len(ks), "salary": bool(sal.get("from") or sal.get("to")),
            "salary_rub_month": bool(sal) and (sal.get("currency") or "RUR") == "RUR"
            and ((sal.get("mode") or {}).get("id") in (None, "MONTH")),
            "neg_exp": bool(NEG_EXP.search(text)), "neg_remote": bool(NEG_REMOTE.search(text)),
            "roles": roles, "archived": bool(v.get("archived")), "area": (v.get("area") or {}).get("name")}


def text_of(v: dict) -> str:
    return f"{v.get('name') or ''}\n{html_to_text(v.get('description'))}"


# ------------------------------------------------------------------ сбор
def _search(cl: HhClient, params: list) -> list[dict]:
    try:
        return cl.get("/vacancies", params, ttl_s=30 * 86400)["data"].get("items") or []
    except HhError as e:
        print("поиск:", e.code, e.message)
        return []


def relabel() -> None:
    """Пересчитать метки по локальному кэшу текстов (без запросов к hh.ru): номера и выборки те же."""
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    for it in corpus["items"]:
        p = CACHE / "raw" / f"{it['id']}.json"
        if p.exists():
            v = json.loads(p.read_text(encoding="utf-8"))
            it["labels"] = labels(v, it["bucket"])
    CORPUS.write_text(json.dumps(corpus, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("метки пересчитаны:", len(corpus["items"]))


def collect(per: int, extra: int) -> None:
    cl = client()
    picked: dict[str, str] = {}
    for d, (roles, words) in ROLE_QUERY.items():
        for g in GRADES:
            text = " AND ".join(([f"NAME:{_q(words)}"] if words else []) + [f"NAME:{_q(GRADE_WORDS[g])}"])
            params = [("text", text)] + [("professional_role", r) for r in roles] + [
                ("area", "113"), ("per_page", "50"), ("order_by", "publication_time")]
            n = 0
            for it in _search(cl, params):
                if it["id"] not in picked and n < per:
                    picked[it["id"]] = f"{d}.{g}"
                    n += 1
            print(f"{d}.{g}: {n}")
    for bucket, phrase, roles in NEG_QUERIES:
        params = [("text", phrase), ("search_field", "description")] + [("professional_role", r) for r in roles] + [
            ("area", "113"), ("per_page", "30"), ("order_by", "publication_time")]
        n = 0
        for it in _search(cl, params):
            if it["id"] not in picked and n < extra:
                picked[it["id"]] = bucket
                n += 1
        print(f"{bucket} {phrase}: {n}")
    raw_dir = CACHE / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for i, (vid, bucket) in enumerate(picked.items(), 1):
        try:
            v = cl.get(f"/vacancies/{vid}", ttl_s=30 * 86400)["data"]
        except HhError as e:
            print(vid, e.code)
            continue
        (raw_dir / f"{vid}.json").write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
        items.append({"id": vid, "url": f"https://hh.ru/vacancy/{vid}", "bucket": bucket, "labels": labels(v, bucket),
                      "text_sha256": hashlib.sha256(text_of(v).encode()).hexdigest()})
        if i % 25 == 0:
            print(f"… {i}/{len(picked)}")
    out = {"schema_version": 1, "collected_at": datetime.now(timezone.utc).date().isoformat(),
           "purpose": "Проверка разбора потребности на реальных вакансиях hh.ru (FTT.6: только тестовые данные). "
                      "В файле — номера, ссылки и производные метки из структурированных полей hh.ru; тексты "
                      "вакансий в репозиторий не входят (локальный кэш HH_CORPUS_DIR, повтор — с токеном приложения).",
           "method": "Поиск GET /vacancies по ролям каталога (5 направлений × 4 грейда: профессиональная роль hh.ru + "
                     "слова направления и грейда в названии, вся Россия, свежие) и выборки с отрицаниями; затем "
                     "GET /vacancies/{id}. Метки: направление — роль hh.ru (+ слова названия для «Программист»), "
                     "грейд — слово в названии, опыт — поле experience, формат — work_format, навыки — key_skills → "
                     "теги справочника; neg_exp / neg_remote — найдено ли отрицание в тексте (регулярное выражение).",
           "n": len(items), "items": items}
    CORPUS.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("корпус:", len(items), "→", CORPUS.relative_to(ROOT))


# ------------------------------------------------------------------ прогон разбора
def parser_at(rev: str):
    """parse_need из need_parser.py ревизии rev (как у Я11, parse_compare.py); словарь и справочник — текущие."""
    src = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{rev}:backend/app/modules/matching/need_parser.py"],
                                  text=True)
    ns: dict = {"__name__": f"need_parser_{rev}"}
    exec(compile(src, f"need_parser@{rev}", "exec"), ns)
    return ns["parse_need"]


def load_texts(items: list[dict], refetch: bool) -> dict[str, dict]:
    out, cl = {}, None
    for it in items:
        p = CACHE / "raw" / f"{it['id']}.json"
        if p.exists():
            out[it["id"]] = json.loads(p.read_text(encoding="utf-8"))
        elif refetch:
            cl = cl or client()
            try:
                v = cl.get(f"/vacancies/{it['id']}", ttl_s=30 * 86400)["data"]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
                out[it["id"]] = v
            except HhError:
                pass
    return out


def _pct(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def measure(items: list[dict], raws: dict[str, dict], parse) -> dict:
    c, tot = Counter(), Counter()
    tp = fn = fp_conf = n_req = 0
    neg = {k: [0, 0, 0] for k in ("neg_exp", "noexp_field", "neg_remote", "onsite_only")}  # верно, всего, явно
    mism = []
    for it in items:
        v = raws.get(it["id"])
        if v is None:
            continue
        lb = it["labels"]
        r = parse(text_of(v), use_llm=False)
        tot["n"] += 1
        for f in FIELDS:
            c[f"found_{f}"] += r.get(f) is not None and r.get(f) != "any"
        req = {s["tag"] for s in r.get("stack_required") or []}
        allst = req | {s["tag"] for s in r.get("stack_desired") or []}
        c["found_stack"] += bool(allst)
        c["found_salary"] += r.get("salary_from") is not None or r.get("salary_to") is not None
        # точность по меткам
        if lb["direction"]:
            tot["direction"] += 1
            ok = r.get("direction") in lb["direction_acceptable"]
            c["direction"] += ok
            if not ok:
                mism.append({"id": it["id"], "field": "direction", "expected": lb["direction"], "actual": r.get("direction")})
        if lb["grade"]:
            tot["grade"] += 1
            ok = r.get("grade") in (lb["grade_acceptable"] or [lb["grade"]])
            c["grade"] += ok
            if not ok:
                mism.append({"id": it["id"], "field": "grade", "expected": lb["grade"], "actual": r.get("grade")})
        if lb["experience"] in EXP_RANGE:
            lo, hi = EXP_RANGE[lb["experience"]]
            x = r.get("experience_years_min")
            tot["experience"] += 1
            if x is not None:
                tot["experience_found"] += 1
                ok = lo <= float(x) <= hi
                c["experience"] += ok
                if not ok:
                    mism.append({"id": it["id"], "field": "experience_years_min", "expected": lb["experience"], "actual": x})
        if lb["work_formats"]:
            tot["work_format"] += 1
            wf = r.get("work_format")
            if wf and wf != "any":
                tot["work_format_found"] += 1
                ok = wf in lb["work_formats"]
                c["work_format"] += ok
                if not ok:
                    mism.append({"id": it["id"], "field": "work_format", "expected": lb["work_formats"], "actual": wf})
        ks = set(lb["key_skills_tags"])
        if ks:
            tot["ks_items"] += 1
            tp += len(ks & allst)
            fn += len(ks - allst)
        n_req += len(req)
        fp_conf += len(req & ks)
        # отрицания
        # отрицания: «верно» — разбор не требует опыта (0 или не указан) / не пишет «удалённо»; явный 0 и «офис» — отдельно
        x = r.get("experience_years_min")
        remote = r.get("work_format") == "remote" or "remote" in (r.get("work_formats") or [])
        if lb["neg_exp"]:
            neg["neg_exp"][1] += 1
            neg["neg_exp"][0] += x in (0, 0.0, None)
            neg["neg_exp"][2] += x in (0, 0.0)
            if x not in (0, 0.0, None):
                mism.append({"id": it["id"], "field": "neg_exp", "expected": 0, "actual": x})
        if lb["experience"] == "noExperience":
            neg["noexp_field"][1] += 1
            neg["noexp_field"][0] += x in (0, 0.0, None)
            neg["noexp_field"][2] += x in (0, 0.0)
        if lb["neg_remote"]:
            neg["neg_remote"][1] += 1
            neg["neg_remote"][0] += not remote
            neg["neg_remote"][2] += r.get("work_format") == "office"
            if remote:
                mism.append({"id": it["id"], "field": "neg_remote", "expected": "не remote", "actual": r.get("work_format")})
        if lb["work_formats"] == ["office"]:
            neg["onsite_only"][1] += 1
            neg["onsite_only"][0] += not remote
            neg["onsite_only"][2] += r.get("work_format") == "office"
    n = tot["n"]
    return {
        "n": n,
        "completeness": {f: _pct(c[f"found_{f}"], n) for f in FIELDS + ["stack", "salary"]},
        "accuracy": {
            "direction": {"correct": c["direction"], "n": tot["direction"], "share": _pct(c["direction"], tot["direction"])},
            "grade": {"correct": c["grade"], "n": tot["grade"], "share": _pct(c["grade"], tot["grade"])},
            "experience": {"consistent": c["experience"], "found": tot["experience_found"], "n": tot["experience"],
                           "share_of_found": _pct(c["experience"], tot["experience_found"])},
            "work_format": {"consistent": c["work_format"], "found": tot["work_format_found"], "n": tot["work_format"],
                            "share_of_found": _pct(c["work_format"], tot["work_format_found"])}},
        "skills": {"vacancies_with_key_skills": tot["ks_items"], "key_skills_recall": _pct(tp, tp + fn),
                   "key_skills_found": tp, "key_skills_total": tp + fn,
                   "required_confirmed_by_key_skills": _pct(fp_conf, n_req), "required_total": n_req},
        "negations": {k: {"correct": a, "n": b, "share": _pct(a, b), "explicit": e, "explicit_share": _pct(e, b)}
                      for k, (a, b, e) in neg.items()},
        "mismatches": mism[:60]}


class _CatalogDb:
    """Справочник категорий без БД (seed_data + рыночные диапазоны миграций не нужны: вилка из hh.ru или пометка)."""

    def get(self, model, key):
        from types import SimpleNamespace

        from app.modules.catalog.seed_data import DIRECTIONS, GRADES

        d, _, g = str(key).partition(".")
        if d in DIRECTIONS and g in GRADES:
            return SimpleNamespace(id=key, market_salary_from=100_000, market_salary_to=150_000)
        return None


def import_completeness(items: list[dict], raws: dict[str, dict]) -> dict:
    """Черновик импорта (map_vacancy: текст + структурированные поля hh.ru) — сколько полей заполнено."""
    from app.modules.hh.importer import map_vacancy

    c, n, db = Counter(), 0, _CatalogDb()
    for it in items:
        v = raws.get(it["id"])
        if v is None:
            continue
        m = map_vacancy(db, v)
        n += 1
        c["category"] += m.category_id is not None
        c["salary_from_hh"] += m.salary_source == "hh"
        c["salary_partial"] += m.salary_source == "hh_partial"
        c["work_format"] += m.work_format != "any"
        c["city"] += bool(m.city)
        c["stack"] += bool(m.stack)
        c["conditions"] += bool(m.conditions)
        c["no_notes"] += not m.notes
    return {"n": n, **{k: _pct(c[k], n) for k in ("category", "salary_from_hh", "salary_partial", "work_format", "city",
                                                    "stack", "conditions", "no_notes")}}


def run(rev: str | None, refetch: bool) -> None:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    items = corpus["items"]
    raws = load_texts(items, refetch)
    changed = sum(1 for it in items if it["id"] in raws
                  and hashlib.sha256(text_of(raws[it["id"]]).encode()).hexdigest() != it["text_sha256"])
    res = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "code_commit": code_commit(),
           "corpus_collected_at": corpus["collected_at"], "n_corpus": len(items), "n": len(raws),
           "missing": len(items) - len(raws), "text_changed_since_collect": changed,
           "buckets": dict(Counter(it["bucket"].split(".")[0] if "." in it["bucket"] else it["bucket"] for it in items)),
           "method": "Путь правил need_parser.parse_need(use_llm=False) на названии и описании (key_skills парсеру не "
                     "даются). Метки — структурированные поля hh.ru: роль → направление, слово грейда в названии → "
                     "грейд, experience → диапазон лет, work_format → формат, key_skills → теги справочника. "
                     "Опыт и формат: «согласовано» — значение парсера внутри поля hh.ru (доля от найденных); "
                     "отрицания — текст с «опыт не требуется» → разбор не требует опыта, «удалёнка не предусмотрена / только офис» → "
                     "не «удалённо» (явные 0 лет и «офис» — отдельно).",
           "parser": measure(items, raws, need_parser.parse_need), "import": import_completeness(items, raws),
           "baseline_note": "Я11 (fix/sup3): тот же замер на 50 вакансиях — reports_0910/sup3.md; здесь — корпус hh.ru."}
    if rev:
        res["compare"] = {"rev": rev, "parser": measure(items, raws, parser_at(rev))}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    OUT_MD.write_text(render_md(res), encoding="utf-8")
    p = res["parser"]
    print(json.dumps({k: p[k] for k in ("n", "completeness", "accuracy", "skills", "negations")}, ensure_ascii=False, indent=1))
    if rev:
        q = res["compare"]["parser"]
        print("compare", rev, json.dumps({k: q[k] for k in ("accuracy", "negations")}, ensure_ascii=False))


def _s(x) -> str:
    return "—" if x is None else f"{x * 100:.1f} %".replace(".", ",")


def render_md(r: dict) -> str:
    p = r["parser"]
    a, sk, ng = p["accuracy"], p["skills"], p["negations"]
    lines = [
        "# Разбор потребности на вакансиях hh.ru (Я12)", "",
        f"Корпус собран {r['corpus_collected_at']}: {r['n_corpus']} вакансий (в прогоне {r['n']}, недоступно "
        f"{r['missing']}, текст изменился с даты сбора: {r['text_changed_since_collect']}). Прогон "
        f"{r['generated_at'][:10]}, код `{r['code_commit']}`. Пересчёт: `cd backend && python "
        "../tools/realdata/hh_corpus.py run` (нужен токен приложения hh.ru; тексты — в локальном кэше).", "",
        "Корпус — только для проверки разбора (ответ организаторов FTT.6: парсинг допустим для тестовых данных, не "
        "как продуктовая механика). В репозитории — номера, ссылки и производные метки "
        "(`docs/realdata/hh_corpus.json`), тексты вакансий не хранятся.", "",
        f"**Методика.** {r['method']} Методика и поля — как у замера Я11 на 50 вакансиях "
        "(`tools/realdata/parse_compare.py`), корпус шире и метки независимы от текста. Метки — серебряные (поля hh.ru "
        "заполняет работодатель; грейд в названии — не экспертная разметка).", "",
        f"Состав: {', '.join(f'{k} {v}' for k, v in sorted(r['buckets'].items()))}.", "",
        "## Полнота полей (что разбор нашёл в тексте)", "",
        "| Поле | Найдено |", "|---|---:|"]
    titles = {"direction": "направление", "grade": "грейд", "experience_years_min": "опыт (лет)",
              "work_format": "формат работы", "stack": "стек (≥ 1 навык)", "salary": "зарплата в тексте"}
    for k, v in p["completeness"].items():
        lines.append(f"| {titles.get(k, k)} | {_s(v)} |")
    lines += ["", "## Совпадение с полями hh.ru", "", "| Поле | Результат |", "|---|---|",
              f"| направление (роль hh.ru) | {a['direction']['correct']} из {a['direction']['n']} — {_s(a['direction']['share'])} |",
              f"| грейд (слово в названии) | {a['grade']['correct']} из {a['grade']['n']} — {_s(a['grade']['share'])} |",
              f"| опыт внутри поля experience | {a['experience']['consistent']} из {a['experience']['found']} найденных — "
              f"{_s(a['experience']['share_of_found'])} (поле есть у {a['experience']['n']}) |",
              f"| формат внутри work_format | {a['work_format']['consistent']} из {a['work_format']['found']} найденных — "
              f"{_s(a['work_format']['share_of_found'])} (поле есть у {a['work_format']['n']}) |",
              "", "## Обязательные навыки и key_skills", "",
              f"- Навыки из key_skills (теги справочника), найденные разбором в тексте: {sk['key_skills_found']} из "
              f"{sk['key_skills_total']} — {_s(sk['key_skills_recall'])} ({sk['vacancies_with_key_skills']} вакансий с key_skills).",
              f"- Обязательные навыки разбора, которые работодатель указал и в key_skills: {_s(sk['required_confirmed_by_key_skills'])} "
              f"из {sk['required_total']} (остальные — в тексте, но не в key_skills: это не обязательно ошибка).", "",
              "## Отрицания", "",
              "«Верно» — разбор не требует опыта (0 или не указан) / не пишет «удалённо»; «явно» — опыт 0 / формат «офис».", "",
              "| Случай | Верно | Явно |", "|---|---|---|",
              f"| «опыт не требуется» / «без опыта» в тексте | {ng['neg_exp']['correct']} из {ng['neg_exp']['n']} — {_s(ng['neg_exp']['share'])} | {_s(ng['neg_exp']['explicit_share'])} |",
              f"| experience = «нет опыта» в hh.ru | {ng['noexp_field']['correct']} из {ng['noexp_field']['n']} — {_s(ng['noexp_field']['share'])} | {_s(ng['noexp_field']['explicit_share'])} |",
              f"| «удалёнка не предусмотрена» / «только офис» в тексте | {ng['neg_remote']['correct']} из {ng['neg_remote']['n']} — {_s(ng['neg_remote']['share'])} | {_s(ng['neg_remote']['explicit_share'])} |",
              f"| work_format = только «на месте» в hh.ru | {ng['onsite_only']['correct']} из {ng['onsite_only']['n']} — {_s(ng['onsite_only']['share'])} | {_s(ng['onsite_only']['explicit_share'])} |"]
    if r.get("import"):
        im = r["import"]
        lines += ["", "## Черновик импорта (текст + поля hh.ru)", "",
                  f"На {im['n']} вакансиях: категория {_s(im['category'])}, вилка из hh.ru целиком (рубли, месяц, ширина ≤ 1,5) "
                  f"{_s(im['salary_from_hh'])}, частично из hh.ru (только «от» или «до», либо шире 1,5) с пометкой «уточните» {_s(im.get('salary_partial'))} "
                  "(в остальных зарплаты в hh.ru нет или она не в рублях за месяц — рыночный диапазон категории), "
                  f"формат {_s(im['work_format'])}, город {_s(im['city'])}, стек {_s(im['stack'])}, "
                  f"строка «Условия с hh.ru» {_s(im['conditions'])}, без пометок «уточните» {_s(im['no_notes'])}."]
    if r.get("compare"):
        q = r["compare"]["parser"]
        lines += ["", f"## Сравнение: парсер ревизии `{r['compare']['rev']}`", "",
                  "| Показатель | Текущий код | " + r["compare"]["rev"] + " |", "|---|---:|---:|"]
        for k, t in (("direction", "направление"), ("grade", "грейд")):
            lines.append(f"| {t} | {_s(a[k]['share'])} | {_s(q['accuracy'][k]['share'])} |")
        for k, t in (("experience", "опыт (доля найденных)"), ("work_format", "формат (доля найденных)")):
            lines.append(f"| {t} | {_s(a[k]['share_of_found'])} ({a[k]['found']}) | {_s(q['accuracy'][k]['share_of_found'])} ({q['accuracy'][k]['found']}) |")
        for k, t in (("neg_exp", "«опыт не требуется» → не требует опыта"), ("noexp_field", "«нет опыта» в hh.ru → не требует опыта"),
                     ("neg_remote", "«удалёнка не предусмотрена» → не «удалённо»"),
                     ("onsite_only", "только «на месте» → не «удалённо»")):
            lines.append(f"| {t} | {_s(ng[k]['share'])} ({ng[k]['n']}) | {_s(q['negations'][k]['share'])} ({q['negations'][k]['n']}) |")
        lines.append(f"| key_skills найдены в тексте | {_s(sk['key_skills_recall'])} | {_s(q['skills']['key_skills_recall'])} |")
    lines += ["", "Расхождения (первые 60, номер вакансии → поле): `backend/app/modules/validation/data/hh_parse.json`.", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--per", type=int, default=8, help="вакансий на направление × грейд")
    c.add_argument("--extra", type=int, default=7, help="вакансий на запрос с отрицанием")
    sub.add_parser("relabel", help="пересчитать метки по локальному кэшу")
    r = sub.add_parser("run")
    r.add_argument("--rev", help="сравнить с need_parser.py этой ревизии (например fix/sup3)")
    r.add_argument("--refetch", action="store_true", help="дочитать отсутствующие тексты с hh.ru (нужен токен)")
    a = ap.parse_args()
    if a.cmd == "collect":
        collect(a.per, a.extra)
    elif a.cmd == "relabel":
        relabel()
    else:
        run(a.rev, a.refetch)


if __name__ == "__main__":
    main()
