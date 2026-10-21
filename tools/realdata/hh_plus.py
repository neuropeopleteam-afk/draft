"""hh.ru сильнее: корпус проверки подбора, снимок рынка зарплат, частоты навыков, спрос по направлениям.

FTT.6: парсинг допустим для наполнения тестовых данных, но не как продуктовая механика — поэтому всё, что отсюда
попадает в продукт, — только агрегаты (медианы, квартили, доли навыков, число вакансий) с n и датой; ни одной чужой
вакансии пользователю не показывается. В репозиторий — номера вакансий, ссылки, наши производные метки и агрегаты;
тексты вакансий — только в локальном кэше вне репозитория (``HH_CORPUS_DIR``). Не чаще 1 запроса/с, кэш ответов.

  set -a; . <файл с HH_APP_TOKEN и HH_USER_AGENT>; set +a       # значения не печатать; токен не перевыпускать
  cd backend
  python ../tools/realdata/hh_plus.py collect   # корпус подбора: 9 направлений × 4 грейда (~8 мин)
  python ../tools/realdata/hh_plus.py demand    # спрос: число вакансий по направлениям и грейдам (~2 мин)
  python ../tools/realdata/hh_plus.py market    # снимок вилок: категория × регион (~6 мин)
  python ../tools/realdata/hh_plus.py skills    # частоты навыков по корпусу (без сети)
  DATABASE_URL=sqlite:///<демо-БД> python ../tools/realdata/hh_plus.py match   # разбор + подбор (без сети)
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools/realdata"))

from app.core.config import Settings  # noqa: E402
from app.integrations.vacancies.ats_import import html_to_text  # noqa: E402
from app.modules.catalog.dictionary import find_stack  # noqa: E402
from app.modules.catalog.seed_data import STACK  # noqa: E402
from app.modules.hh.client import HhClient, HhError  # noqa: E402
from app.modules.hh.directions import GRADE_WORDS, HH_DIRECTIONS, NEW_DIRECTIONS, search_params  # noqa: E402

# сырьё корпуса (тексты вакансий) — только вне репозитория: HH_CORPUS_DIR, по умолчанию ../data_local/hh_corpus
CACHE = Path(os.environ.get("HH_CORPUS_DIR") or ROOT.parent / "data_local/hh_corpus")
# HH_MATCH_CORPUS — другой корпус (отложенный набор tools/realdata/hh_holdout.py); по умолчанию — набор разработки (414)
CORPUS = Path(os.environ["HH_MATCH_CORPUS"]) if os.environ.get("HH_MATCH_CORPUS") else ROOT / "docs/realdata/hh_match_corpus.json"
DATA = ROOT / "backend/app/modules/hh/data"
# HH_MATCH_OUT — каталог для абляций (json и md туда, файлы репозитория не трогаются)
_ABL = os.environ.get("HH_MATCH_OUT")
OUT_MATCH = Path(_ABL) / "hh_match.json" if _ABL else ROOT / "backend/app/modules/validation/data/hh_match.json"
MD_MATCH = Path(_ABL) / "HH_MATCH.md" if _ABL else ROOT / "docs/validation/HH_MATCH.md"
MD_DEMAND = ROOT / "docs/realdata/HH_DEMAND.md"
GRADES = ["intern", "junior", "middle", "senior"]
# Добор корпуса, если вакансий со словом грейда в названии мало: опыт hh.ru (непересекающиеся диапазоны)
TOPUP_EXPERIENCE = {"intern": "noExperience", "junior": "between1And3", "middle": "between3And6", "senior": "moreThan6"}
SNAPSHOT_AREAS = [("113", "Россия"), ("1", "Москва"), ("2", "Санкт-Петербург"), ("3", "Екатеринбург"),
                  ("4", "Новосибирск"), ("88", "Казань")]
GRADE_RX = [("intern", re.compile(r"стаж[её]р|intern|trainee|стажировк", re.I)),
            ("junior", re.compile(r"junior|джун|младш", re.I)),
            ("middle", re.compile(r"middle|мидл", re.I)),
            ("senior", re.compile(r"senior|сеньор|синьор|старш|ведущ|\blead\b|тимлид|team ?lead", re.I))]
LABEL_NOTE = "тексты — реальные вакансии hh.ru, кандидаты — модельные (модель, не люди)"


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


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


def search(cl: HhClient, params: list, ttl: int = 7 * 86400, tries: int = 4) -> dict:
    """GET /vacancies с повтором при тайм-ауте и сбое hh.ru (до tries раз); неудача — пустой ответ с failed=True,
    такая ячейка в снимок не попадает как «0 вакансий» (см. market_snapshot)."""
    for i in range(tries):
        try:
            return cl.get("/vacancies", params, ttl_s=ttl)
        except HhError as e:
            print("поиск:", e.code, e.message, f"(попытка {i + 1} из {tries})")
            if e.code not in ("hh_timeout", "hh_unavailable", "hh_rate_limited"):
                break
    return {"data": {"items": [], "found": 0}, "fetched_at": None, "failed": True}


def detail(cl: HhClient | None, vid: str) -> dict | None:
    p = CACHE / "raw" / f"{vid}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    if cl is None:
        return None
    try:
        v = cl.get(f"/vacancies/{vid}", ttl_s=30 * 86400)["data"]
    except HhError as e:
        print(vid, e.code)
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
    return v


def text_of(v: dict) -> str:
    return f"{v.get('name') or ''}\n{html_to_text(v.get('description'))}"


def title_grade(title: str) -> str | None:
    found = [g for g, rx in GRADE_RX if rx.search(title)]
    return (found[-1] if len(found) > 1 else found[0]) if found else None


def ks_tags(v: dict) -> list[str]:
    return sorted({t for s in v.get("key_skills") or [] for t in find_stack(s.get("name", "")) if t in STACK})


def labels(v: dict, direction: str, grade: str, by: str) -> dict:
    sal = v.get("salary_range") or v.get("salary") or {}
    return {"direction": direction, "grade_bucket": grade, "grade_by": by, "grade_title": title_grade(v.get("name") or ""),
            "experience": (v.get("experience") or {}).get("id"), "key_skills_tags": ks_tags(v),
            "n_key_skills": len(v.get("key_skills") or []), "salary": bool(sal.get("from") or sal.get("to")),
            "area": (v.get("area") or {}).get("name"), "roles": [r.get("id") for r in v.get("professional_roles") or []],
            "archived": bool(v.get("archived"))}


# ------------------------------------------------------------------ корпус подбора
def collect(per: int) -> None:
    cl = client()
    picked: dict[str, tuple[str, str, str]] = {}
    for d in HH_DIRECTIONS:
        for g in GRADES:
            n = 0
            for it in search(cl, search_params(d, g, "113", per_page=50))["data"].get("items") or []:
                if it["id"] not in picked and n < per:
                    picked[it["id"]] = (d, g, "name")
                    n += 1
            m = 0
            if n < per:
                ps = search_params(d, None, "113", per_page=50, experience=[TOPUP_EXPERIENCE[g]])
                for it in search(cl, ps)["data"].get("items") or []:
                    if it["id"] not in picked and n + m < per:
                        picked[it["id"]] = (d, g, "experience")
                        m += 1
            print(f"{d}.{g}: {n} по названию + {m} по опыту")
    items = []
    for i, (vid, (d, g, by)) in enumerate(picked.items(), 1):
        v = detail(cl, vid)
        if v is None:
            continue
        items.append({"id": vid, "url": f"https://hh.ru/vacancy/{vid}", "bucket": f"{d}.{g}", "labels": labels(v, d, g, by),
                      "text_sha256": hashlib.sha256(text_of(v).encode()).hexdigest()})
        if i % 50 == 0:
            print(f"… {i}/{len(picked)}")
    out = {"schema_version": 1, "collected_at": today(), "label_note": LABEL_NOTE,
           "purpose": "Проверка разбора и подбора на реальных вакансиях hh.ru (FTT.6: только тестовые данные). В файле — "
                      "номера, ссылки и производные метки из структурированных полей hh.ru; тексты вакансий в "
                      "репозиторий не входят (локальный кэш HH_CORPUS_DIR, повтор — с токеном приложения).",
           "method": "GET /vacancies по 9 направлениям каталога (включая 4 новых) × 4 грейда: профессиональная роль hh.ru "
                     "+ слова направления в названии (backend/app/modules/hh/directions.py) + слово грейда в названии, "
                     f"вся Россия, свежие; до {per} на ячейку, добор — по опыту hh.ru; затем GET /vacancies/{{id}}.",
           "n": len(items), "items": items}
    CORPUS.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("корпус:", len(items), "→", CORPUS.relative_to(ROOT))


# ------------------------------------------------------------------ спрос
def demand() -> None:
    cl = client()
    rows, as_of = {}, None
    for d, cfg in HH_DIRECTIONS.items():
        r = {"title": cfg["title"], "new": d in NEW_DIRECTIONS}
        for aid, key in (("113", "russia"), ("1", "moscow"), ("2", "spb")):
            res = search(cl, search_params(d, None, aid, per_page=1), ttl=86400)
            r[key] = int(res["data"].get("found") or 0)
            as_of = as_of or res.get("fetched_at")
        r["with_salary_russia"] = int(search(cl, search_params(d, None, "113", per_page=1, with_salary=True),
                                             ttl=86400)["data"].get("found") or 0)
        r["by_grade_title"] = {g: int(search(cl, search_params(d, g, "113", per_page=1), ttl=86400)["data"]
                                      .get("found") or 0) for g in GRADES}
        r["no_experience"] = int(search(cl, search_params(d, None, "113", per_page=1, experience=["noExperience"]),
                                        ttl=86400)["data"].get("found") or 0)
        rows[d] = r
        print(d, r["russia"], r["moscow"], r["spb"])
    out = {"as_of": as_of or datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": "api.hh.ru GET /vacancies (found)",
           "method": "Число открытых вакансий в поиске hh.ru на дату: профессиональная роль + слова направления в названии "
                     "(backend/app/modules/hh/directions.py); грейд — слово грейда в названии; «без опыта» — "
                     "experience=noExperience. Для общих ролей («Программист, разработчик» и др.) это нижняя оценка: "
                     "вакансия считается, только если слово направления есть в названии. Направления пересекаются мало "
                     "(слова-исключения), но не нулём. Это поиск API hh.ru для приложения; на сайте hh.ru число может "
                     "отличаться.",
           "directions": rows}
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "demand.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    MD_DEMAND.write_text(render_demand(out), encoding="utf-8")
    print("спрос →", MD_DEMAND.relative_to(ROOT))


def _n(x: int) -> str:
    return f"{x:,}".replace(",", " ")


def render_demand(r: dict) -> str:
    rows = r["directions"]
    tot = sum(x["russia"] for x in rows.values())
    lines = ["# Спрос по направлениям каталога на hh.ru", "",
             f"Дата: {r['as_of'][:10]} (api.hh.ru, число открытых вакансий в поиске). Пересчёт: "
             "`cd backend && python ../tools/realdata/hh_plus.py demand` (нужен токен приложения hh.ru).", "",
             f"**Как считали.** {r['method']}", "",
             "Используется для обоснования каталога (какие направления добавлять) и в презентации. Это объявления "
             "работодателей, а не число рабочих мест; в продукте чужие вакансии не показываются (FTT.6).", "",
             "| Направление | Россия | Москва | Санкт-Петербург | С зарплатой (Россия) | Без опыта | Стажёр* | Junior* | Middle* | Senior* | Доля |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for d, x in sorted(rows.items(), key=lambda kv: -kv[1]["russia"]):
        g = x["by_grade_title"]
        share = f"{100 * x['russia'] / tot:.1f} %".replace(".", ",") if tot else "—"
        lines.append(f"| {x['title']}{' (новое)' if x['new'] else ''} | {_n(x['russia'])} | {_n(x['moscow'])} | {_n(x['spb'])} | "
                     f"{_n(x['with_salary_russia'])} | {_n(x['no_experience'])} | {_n(g['intern'])} | {_n(g['junior'])} | "
                     f"{_n(g['middle'])} | {_n(g['senior'])} | {share} |")
    new = sum(x["russia"] for d, x in rows.items() if x["new"])
    lines += ["", "\\* — слово грейда в названии вакансии (большинство вакансий грейд в названии не пишут).", "",
              f"Четыре новых направления (DevOps / SRE, инженер данных, мобильная разработка, системный / бизнес-аналитик) — "
              f"{_n(new)} из {_n(tot)} вакансий девяти направлений ({100 * new / tot:.0f} %)." if tot else "", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------ снимок рынка вилок (для индекса доверия)
def market_snapshot() -> None:
    from app.modules.hh.market import MIN_OK, _pct, _r1000, _stats

    cl = client()
    cats, as_of, failed = {}, None, 0
    for d in HH_DIRECTIONS:
        for g in GRADES:
            for aid, aname in SNAPSHOT_AREAS:
                best = None
                for by in ("name", "experience"):
                    from app.modules.hh.market import GRADE_EXPERIENCE

                    ps = search_params(d, g if by == "name" else None, aid, with_salary=True,
                                       experience=GRADE_EXPERIENCE[g] if by == "experience" else None)
                    res = search(cl, ps, ttl=86400)
                    if res.get("failed"):
                        failed += 1
                        continue
                    st = _stats(res["data"].get("items") or [])
                    as_of = as_of or res.get("fetched_at")
                    cur = {"by": by, "st": st, "found": int(res["data"].get("found") or 0)}
                    if best is None or len(st["vals"]) > len(best["st"]["vals"]):
                        best = cur
                    if len(st["vals"]) >= MIN_OK:
                        best = cur
                        break
                if best is None:  # обе ступени не ответили — ячейки нет (а не «0 вакансий»)
                    continue
                vals = best["st"]["vals"]
                e = {"n": len(vals), "by": best["by"], "found": best["found"],
                     "gross_share": round(best["st"]["gross"] / len(vals), 2) if vals else None}
                if vals:
                    e.update(median=_r1000(int(statistics.median(vals))), p25=_r1000(_pct(vals, 0.25)),
                             p75=_r1000(_pct(vals, 0.75)))
                cats.setdefault(f"{d}.{g}", {})[aid] = e
            print(d, g, {a: x["n"] for a, x in cats.get(f"{d}.{g}", {}).items()})
    out = {"as_of": as_of or datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "areas": dict(SNAPSHOT_AREAS), "basis": "net",
           "method": "Вилки в живых вакансиях hh.ru с зарплатой (only_with_salary, до 100 свежих на запрос): рубли за месяц, "
                     "у вилки — середина, у «от» — «от», у «до» — «до»; суммы до вычета НДФЛ приведены к «на руки». Грейд — "
                     "слово грейда в названии, если таких меньше 20 — опыт hh.ru как приближение. Это объявления "
                     "работодателей, не фактические зарплаты.",
           "failed_requests": failed, "categories": cats}
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "market_snapshot.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("снимок рынка →", (DATA / "market_snapshot.json").relative_to(ROOT))


# ------------------------------------------------------------------ частоты навыков
def _load_corpus() -> tuple[dict, list[dict], dict[str, dict]]:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    raws = {it["id"]: v for it in corpus["items"] if (v := detail(None, it["id"])) is not None}
    return corpus, corpus["items"], raws


def skills() -> None:
    from app.modules.matching import need_parser

    corpus, items, raws = _load_corpus()
    by_dir: dict[str, list[set]] = defaultdict(list)
    by_cat: dict[str, list[set]] = defaultdict(list)
    names: dict[str, Counter] = defaultdict(Counter)
    anchor: dict[str, set] = defaultdict(set)  # теги, которые работодатели направления сами указали в key_skills
    for it in items:
        v = raws.get(it["id"])
        if v is None:
            continue
        r = need_parser.parse_need(text_of(v), use_llm=False)
        tags = set(ks_tags(v)) | {s["tag"] for s in (r.get("stack_required") or []) + (r.get("stack_desired") or [])}
        d = it["labels"]["direction"]
        anchor[d] |= set(ks_tags(v))
        by_dir[d].append(tags)
        g = it["labels"]["grade_title"] or (it["labels"]["grade_bucket"] if it["labels"]["grade_by"] == "name" else None)
        if g:
            by_cat[f"{d}.{g}"].append(tags)
        for s in v.get("key_skills") or []:
            nm = " ".join((s.get("name") or "").split())
            if nm:
                names[d][nm] += 1

    def top(rows: list[set], d: str, k: int = 15) -> list[dict]:
        # Навык из текста считается, только если работодатели направления хотя бы раз указали его в key_skills:
        # так отсекаются ложные срабатывания словаря («в пешей доступности» → доступность интерфейсов и т. п.)
        c = Counter(t for r in rows for t in r if t in anchor[d])
        return [{"tag": t, "title": STACK[t][0], "share": round(n / len(rows), 3), "n": n}
                for t, n in c.most_common(k) if n >= 2]

    out = {"as_of": corpus["collected_at"], "source": "корпус hh.ru docs/realdata/hh_match_corpus.json",
           "method": "Доля вакансий направления, где навык есть в «Ключевых навыках» hh.ru или найден разбором текста "
                     "(теги справочника платформы — то, что проверяет тест); навык из текста учитывается, только если "
                     "работодатели направления хотя бы раз указали его в «Ключевых навыках» (отсекает ложные "
                     "срабатывания словаря). Категория (направление × грейд) — только при n ≥ 10 вакансий со словом "
                     "грейда.",
           "min_n_category": 10,
           "directions": {d: {"n": len(rows), "top": top(rows, d)} for d, rows in sorted(by_dir.items())},
           "categories": {c: {"n": len(rows), "top": top(rows, c.split(".")[0])} for c, rows in sorted(by_cat.items())
                          if len(rows) >= 10},
           "key_skills_names_top": {d: [{"name": n, "count": k} for n, k in c.most_common(25)] for d, c in sorted(names.items())}}
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "skills.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("навыки →", (DATA / "skills.json").relative_to(ROOT), {d: x["n"] for d, x in out["directions"].items()})


# ------------------------------------------------------------------ разбор + подбор
def testable_reach(direction: str | None) -> set[str]:
    """Проверяемое ядро направления: теги, которые банк теста подтверждает напрямую (bank_tags) или через implied
    (подтверждённый фреймворк → базовый язык). Обязательный навык вне ядра не может получить T1 ни у одного кандидата —
    его покрытие ограничено потолком, а не качеством подбора."""
    if not direction:
        return set()
    from app.modules.matching import implied
    from app.modules.matching.coverage import bank_tags

    reach = set(bank_tags(direction))
    for src, tgts in implied.IMPLIES.items():
        if src in reach:
            reach.update(tgts)
    return reach


def t1_confirmed_tags(x: dict, tags: set[str]) -> set[str]:
    """Обязательные навыки из tags, подтверждённые тестом (T1, в т. ч. через implied) у строки подборки x."""
    from app.modules.catalog.seed_data import tag_title

    by_title = {f"Обязательно: {tag_title(t)}": t for t in tags}
    return {by_title[r["requirement"]] for r in x.get("reasons") or []
            if r.get("requirement") in by_title and r.get("level") == "T1" and r.get("status") == "confirmed"}


def match(limit: int) -> None:
    from sqlalchemy import select

    from app.core.db import SessionLocal, get_engine
    from app.modules.catalog.models import Category
    from app.modules.catalog.seed_data import DIRECTIONS
    from app.modules.matching import grade_above, need_parser
    from app.modules.matching.ranking import algorithm, build_selection

    from app.modules.catalog import ext as catalog_ext

    # W1: направления каталога — видимые сейчас (5 базовых; с CATALOG_EXT_ENABLED и банком — все 9)
    DIRECTIONS = [d for d in HH_DIRECTIONS if d in DIRECTIONS or catalog_ext.is_visible(d)]  # noqa: N806
    corpus, items, raws = _load_corpus()
    get_engine()
    per = defaultdict(Counter)
    parsed_dir = defaultdict(Counter)
    errors, missed_ks = [], defaultdict(Counter)
    cov_best, cov_mean = defaultdict(list), defaultdict(list)
    # Честные нормированные метрики (20.10): покрытие обязательного только по проверяемому ядру направления (банк +
    # implied) и потолок — какая доля обязательных навыков вакансии вообще может быть подтверждена тестом
    cov_best_t, ceil_v = defaultdict(list), defaultdict(list)
    compare = os.environ.get("HH_MATCH_COMPARE", "1") != "0"
    with SessionLocal() as db:
        cat_ids = {c.id for c in db.scalars(select(Category)).all()}
        for i, it in enumerate(items, 1):
            v = raws.get(it["id"])
            if v is None:
                continue
            lb = it["labels"]
            d = lb["direction"]
            in_catalog = d in DIRECTIONS
            r = need_parser.parse_need(text_of(v), use_llm=False)
            c = per[d]
            c["n"] += 1
            parsed_dir[d][r.get("direction") or "—"] += 1
            req = {s["tag"] for s in r.get("stack_required") or []}
            des = {s["tag"] for s in r.get("stack_desired") or []}
            ks = set(lb["key_skills_tags"])
            c["with_required"] += bool(req)
            c["n_required"] += len(req)
            if ks:
                c["ks_vac"] += 1
                c["ks_total"] += len(ks)
                c["ks_found"] += len(ks & (req | des))
                for t in ks - (req | des):
                    missed_ks[d][t] += 1
            if in_catalog:
                c["dir_labelled"] += 1
                ok = r.get("direction") == d
                c["dir_ok"] += ok
                if not ok:
                    errors.append({"id": it["id"], "field": "direction", "expected": d, "actual": r.get("direction")})
            gt = lb["grade_title"]
            if gt:
                c["grade_labelled"] += 1
                c["grade_ok"] += r.get("grade") == gt
                if r.get("grade") != gt:
                    errors.append({"id": it["id"], "field": "grade", "expected": gt, "actual": r.get("grade")})
            if not req and not des:
                errors.append({"id": it["id"], "field": "stack", "expected": "≥ 1 навык", "actual": None})
            exact = f"{r.get('direction')}.{r.get('grade')}" if r.get("direction") and r.get("grade") else None
            # Я12б: «до» — тот же код с выключенным добором ступенью выше (MATCH_GRADE_ABOVE=0, match-v1.2), «после» —
            # продукт по умолчанию; покрытие обязательного и «найден подтверждённый» — для обоих
            for pre, flag in (("off_", "0"), ("", None)) if compare else (("", None),):
                prev = os.environ.get(grade_above.FLAG)
                if flag is not None:
                    os.environ[grade_above.FLAG] = flag
                try:
                    sel = build_selection(db, r, {}, limit=limit)
                finally:
                    if flag is not None:
                        os.environ.pop(grade_above.FLAG) if prev is None else os.environ.__setitem__(grade_above.FLAG, prev)
                res = sel["results"]
                conf = [x for x in res if x["grade_status"] == "confirmed"]
                c[pre + "selection_nonempty"] += bool(res)
                c[pre + "confirmed_any"] += bool(conf)
                c[pre + "confirmed_exact"] += bool(exact and exact in cat_ids and any(x["category_id"] == exact for x in conf))
                c[pre + "confirmed_right_direction"] += bool(any((x["category_id"] or "").split(".")[0] == d for x in conf))
                c[pre + "grade_above_applied"] += bool((sel.get("grade_above") or {}).get("applied"))
                top5 = [x for x in res[:5]]
                above_id = (sel.get("grade_above") or {}).get("above")
                c[pre + "top5_slots"] += len(top5)
                c[pre + "top5_above"] += sum(1 for x in top5 if above_id and x["category_id"] == above_id)
                if req:
                    c[pre + "req_vac"] += 1
                    vals = [x["components"].get("stack_required") or 0 for x in top5]
                    cov_best[pre + d].append(max(vals, default=0.0))
                    cov_mean[pre + d].append(statistics.mean(vals) if vals else 0.0)
                    c[pre + "req_full_top5"] += any((x.get("must") or {}).get("missing_total", 1) == 0 for x in top5)
                    c[pre + "req_full_top5_conf"] += any((x.get("must") or {}).get("missing_total", 1) == 0
                                                         and x["grade_status"] == "confirmed" for x in top5)
                    if pre == "":  # нормированные метрики — для продукта по умолчанию
                        req_t = req & testable_reach(r.get("direction"))
                        ceil_v[d].append(len(req_t) / len(req))
                        if req_t:
                            c["req_vac_t"] += 1
                            got = [len(t1_confirmed_tags(x, req_t)) / len(req_t) for x in top5]
                            cov_best_t[d].append(max(got, default=0.0))
                            c["req_full_top5_t"] += any(g >= 1.0 for g in got)
            if i % 50 == 0:
                print(f"… {i}/{len(items)}")
    dirs = {}
    for d, c in per.items():
        cv = cov_best[d]
        dirs[d] = {"title": HH_DIRECTIONS[d]["title"], "in_catalog": d in DIRECTIONS, "n": c["n"],
                   "parsed_direction": dict(parsed_dir[d].most_common()),
                   "direction_ok": _share(c["dir_ok"], c["dir_labelled"]), "grade_ok": _share(c["grade_ok"], c["grade_labelled"]),
                   "with_required": _share(c["with_required"], c["n"]),
                   "key_skills_recall": _share(c["ks_found"], c["ks_total"]),
                   "selection_nonempty": _share(c["selection_nonempty"], c["n"]),
                   "confirmed_any": _share(c["confirmed_any"], c["n"]),
                   "confirmed_exact": _share(c["confirmed_exact"], c["n"]),
                   "confirmed_right_direction": _share(c["confirmed_right_direction"], c["n"]),
                   "req_coverage_best_top5": {"mean": round(statistics.mean(cv), 3) if cv else None, "n": len(cv)},
                   "req_coverage_mean_top5": _mean(cov_mean[d]),
                   "req_coverage_best_top5_off": _mean(cov_best["off_" + d]),
                   "req_full_top5": _share(c["req_full_top5"], c["req_vac"]),
                   "req_full_top5_confirmed": _share(c["req_full_top5_conf"], c["req_vac"]),
                   **_testable(cov_best_t[d], ceil_v[d], c),
                   "missed_key_skills_top": [{"tag": t, "n": k} for t, k in missed_ks[d].most_common(5)]}
    tot = Counter()
    for c in per.values():
        tot.update(c)
    allcv = [x for d in per for x in cov_best[d]]
    catalog = [d for d in per if d in DIRECTIONS]
    cat_tot = Counter()
    for d in catalog:
        cat_tot.update(per[d])

    def covs(ds):
        return {k: [x for d in ds for x in src[pre + d]] for k, src, pre in (
            ("mean5", cov_mean, ""), ("best5_off", cov_best, "off_"), ("mean5_off", cov_mean, "off_"),
            ("best5_t", cov_best_t, ""), ("ceil", ceil_v, ""))}
    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "code_commit": code_commit(),
           "algorithm": algorithm(), "label_note": LABEL_NOTE, "corpus_collected_at": corpus["collected_at"],
           "n_corpus": len(items), "n": tot["n"], "n_missing": len(items) - tot["n"], "limit": limit,
           "catalog_directions": sorted(DIRECTIONS),
           "method": "Текст вакансии (название + описание) → разбор потребности путём правил (parse_need, без LLM) → "
                     "подборка (build_selection, настройки по умолчанию) на демо-пуле: модельные кандидаты с результатами "
                     "теста (модель, не люди). Метки — из полей hh.ru: направление — роль и слова названия, грейд — слово "
                     "в названии, навыки — «Ключевые навыки» → теги справочника (разбору не даются). «Подтверждённые» — "
                     "кандидаты, у которых грейд подтверждён тестом. Покрытие требований — доля обязательных навыков "
                     "потребности, подтверждённых тестом (T1), у лучшего из первых пяти; подтверждённый фреймворк "
                     "засчитывается как подтверждение базового языка (FastAPI/Django → Python, React/Vue → JavaScript, "
                     "Spring → Java, PostgreSQL → SQL, Docker/Kubernetes → Linux; балл × 0,9; флаг MATCH_IMPLIED, "
                     "matching/implied.py). Нормированные метрики (поля *_testable и ceiling): проверяемое ядро — "
                     "обязательные навыки, которые банк направления подтверждает тестом напрямую или через implied; "
                     "ceiling — средняя по вакансиям доля таких навыков среди всех обязательных (максимум сырого "
                     "покрытия при идеальном пуле); req_coverage_best_top5_testable — доля навыков ядра, подтверждённых "
                     "у лучшего из пяти; req_full_top5_testable — в пятёрке есть кандидат со всем ядром.",
           "implied": os.environ.get("MATCH_IMPLIED", "1"),
           "overall": _summary(tot, allcv, covs(list(per))),
           "catalog_only": _summary(cat_tot, [x for d in catalog for x in cov_best[d]], covs(catalog)),
           "grade_above": {"compare": compare, "flag": grade_above.FLAG, "min_exact": grade_above.MIN_EXACT,
                           "keep": grade_above.KEEP,
                           "note": "«до» — тот же код и разбор с MATCH_GRADE_ABOVE=0 (match-v1.2), «после» — продукт "
                                   "по умолчанию (match-v1.3): в точной категории меньше 30 подтверждённых — добор "
                                   "категории на ступень выше, первые 2 места — лучшие точного уровня"},
           "directions": dict(sorted(dirs.items())),
           "errors_top": errors[:80], "errors_by_field": dict(Counter(e["field"] for e in errors))}
    OUT_MATCH.parent.mkdir(parents=True, exist_ok=True)
    OUT_MATCH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    MD_MATCH.write_text(render_match(out), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("n", "overall", "catalog_only")}, ensure_ascii=False, indent=1))


def _share(a: int, b: int) -> dict:
    return {"k": a, "n": b, "share": round(a / b, 3) if b else None}


def _testable(best_t: list[float], ceil: list[float], c: Counter, raw: list[float] | None = None) -> dict:
    """Нормированные метрики проверяемого ядра рядом с сырыми; raw_to_ceiling — сырое покрытие / потолок."""
    out = {"req_coverage_best_top5_testable": _mean(best_t),
           "req_full_top5_testable": _share(c["req_full_top5_t"], c["req_vac_t"]),
           "ceiling": _mean(ceil)}
    if raw and ceil and statistics.mean(ceil):
        out["req_coverage_best_top5_raw_to_ceiling"] = round(statistics.mean(raw) / statistics.mean(ceil), 3)
    return out


def _mean(v: list[float]) -> dict:
    return {"mean": round(statistics.mean(v), 3) if v else None, "n": len(v)}


def _summary(c: Counter, cv: list[float], extra: dict | None = None) -> dict:
    extra = extra or {}
    off = {"selection_nonempty": _share(c["off_selection_nonempty"], c["n"]),
           "confirmed_any": _share(c["off_confirmed_any"], c["n"]),
           "confirmed_exact": _share(c["off_confirmed_exact"], c["n"]),
           "confirmed_right_direction": _share(c["off_confirmed_right_direction"], c["n"]),
           "req_coverage_best_top5": _mean(extra.get("best5_off") or []),
           "req_coverage_mean_top5": _mean(extra.get("mean5_off") or []),
           "req_full_top5": _share(c["off_req_full_top5"], c["off_req_vac"]),
           "req_full_top5_confirmed": _share(c["off_req_full_top5_conf"], c["off_req_vac"])} if c["off_req_vac"] else None
    return {"n": c["n"], "direction_ok": _share(c["dir_ok"], c["dir_labelled"]), "grade_ok": _share(c["grade_ok"], c["grade_labelled"]),
            "req_coverage_mean_top5": _mean(extra.get("mean5") or []),
            "grade_above_applied": _share(c["grade_above_applied"], c["n"]),
            "top5_above_share": _share(c["top5_above"], c["top5_slots"]),
            "grade_above_off": off,
            "with_required": _share(c["with_required"], c["n"]), "key_skills_recall": _share(c["ks_found"], c["ks_total"]),
            "selection_nonempty": _share(c["selection_nonempty"], c["n"]), "confirmed_any": _share(c["confirmed_any"], c["n"]),
            "confirmed_exact": _share(c["confirmed_exact"], c["n"]),
            "confirmed_right_direction": _share(c["confirmed_right_direction"], c["n"]),
            "req_coverage_best_top5": {"mean": round(statistics.mean(cv), 3) if cv else None, "n": len(cv)},
            "req_full_top5": _share(c["req_full_top5"], c["req_vac"]),
            "req_full_top5_confirmed": _share(c["req_full_top5_conf"], c["req_vac"]),
            "required_mean": round(c["n_required"] / c["with_required"], 1) if c["with_required"] else None,
            **_testable(extra.get("best5_t") or [], extra.get("ceil") or [], c, cv)}


def _p(x: dict | None) -> str:
    if not x or x.get("share") is None:
        return "—"
    return f"{x['share'] * 100:.1f} % ({x['k']} из {x['n']})".replace(".", ",", 1)


def _m(x: dict) -> str:
    return "—" if x.get("mean") is None else f"{x['mean'] * 100:.1f} %".replace(".", ",")


def render_match(r: dict) -> str:
    o, k = r["overall"], r["catalog_only"]
    lines = ["# Подбор на реальных вакансиях hh.ru", "",
             f"**{LABEL_NOTE[0].upper() + LABEL_NOTE[1:]}.** Корпус собран {r['corpus_collected_at']}: {r['n_corpus']} вакансий "
             f"девяти направлений (в прогоне {r['n']}, недоступно {r['n_missing']}). Прогон {r['generated_at'][:10]}, код "
             f"`{r['code_commit']}`, алгоритм `{r['algorithm']}`. Пересчёт: `cd backend && DATABASE_URL=sqlite:///<демо-БД> "
             "python ../tools/realdata/hh_plus.py match` с `CATALOG_EXT_ENABLED=1` (все 9 направлений) и `HH_CORPUS_DIR=<сырые вакансии>` "
             "(демо-БД: `alembic upgrade head` + `python -m app.modules.demo.seed` с тем же флагом).", "",
             f"**Методика.** {r['method']}", "",
             "В репозитории — номера вакансий, ссылки и производные метки (`docs/realdata/hh_match_corpus.json`); тексты "
             "вакансий не хранятся (FTT.6: парсинг — только для тестовых данных).", "",
             "## Итог", "", "| Показатель | Направления каталога | Все 9 направлений |", "|---|---|---|"]
    for key, t in (("direction_ok", "направление разобрано верно (роль hh.ru)"), ("grade_ok", "грейд разобран верно (слово в названии)"),
                   ("with_required", "в потребности есть обязательные навыки"), ("key_skills_recall", "«Ключевые навыки» hh.ru найдены разбором"),
                   ("selection_nonempty", "подборка не пуста"), ("confirmed_any", "есть кандидат с подтверждённым тестом грейдом"),
                   ("confirmed_exact", "… в точной категории потребности"), ("confirmed_right_direction", "… в направлении вакансии"),
                   ("req_full_top5", "в первой пятёрке есть кандидат со всеми обязательными навыками"),
                   ("req_full_top5_confirmed", "… и с подтверждённым грейдом")):
        lines.append(f"| {t} | {_p(k[key])} | {_p(o[key])} |")
    lines.append(f"| покрытие обязательных навыков у лучшего из пяти (среднее, T1) | {_m(k['req_coverage_best_top5'])} | "
                 f"{_m(o['req_coverage_best_top5'])} |")
    if k.get("req_coverage_mean_top5"):
        lines.append(f"| … в среднем по первой пятёрке (T1) | {_m(k['req_coverage_mean_top5'])} | "
                     f"{_m(o['req_coverage_mean_top5'])} |")
    if k.get("req_coverage_best_top5_testable"):
        lines += [f"| потолок: доля обязательных, которые тест в принципе может подтвердить (ceiling) | "
                  f"{_m(k['ceiling'])} | {_m(o['ceiling'])} |",
                  f"| покрытие проверяемого ядра у лучшего из пяти (T1, нормировано) | "
                  f"{_m(k['req_coverage_best_top5_testable'])} | {_m(o['req_coverage_best_top5_testable'])} |",
                  f"| в пятёрке есть кандидат со всем проверяемым ядром | {_p(k['req_full_top5_testable'])} | "
                  f"{_p(o['req_full_top5_testable'])} |"]
    if k.get("required_mean") is not None:
        lines.append(f"| обязательных навыков в потребности (среднее, где они есть) | {str(k['required_mean']).replace('.', ',')} | "
                     f"{str(o['required_mean']).replace('.', ',')} |")
    if k.get("grade_above_off"):
        ko, oo = k["grade_above_off"], o["grade_above_off"]
        lines += ["", "## Добор уровнем выше (match-v1.3): до и после", "",
                  "«До» — тот же код и тот же разбор с `MATCH_GRADE_ABOVE=0` (порядок match-v1.2: только точная категория), "
                  "«после» — продукт по умолчанию: если в точной категории меньше 30 кандидатов с подтверждённым или "
                  "предварительным грейдом, подборка добавляет категорию на ступень выше; первые 2 места — лучшие точного "
                  "уровня, дальше кандидат уровнем выше стоит выше точного, только если покрывает больше обязательного. "
                  f"Добор сработал: {_p(k['grade_above_applied'])} вакансий каталога; доля кандидатов уровнем выше в "
                  f"первых пятёрках — {_p(k['top5_above_share'])}. На синтетике со скрытой истиной правило не ухудшает "
                  "P@5, P@10, nDCG@5, nDCG@10 и MRR ни в одном из шести миров — `docs/validation/grade_above.json`.", "",
                  "| Показатель (направления каталога) | До (match-v1.2) | После (match-v1.3) | Все 9: до | Все 9: после |",
                  "|---|---|---|---|---|"]
        for key, t, f in (("req_coverage_best_top5", "покрытие обязательных у лучшего из пяти", _m),
                          ("req_coverage_mean_top5", "покрытие обязательных, среднее по пятёрке", _m),
                          ("req_full_top5", "в пятёрке есть кандидат со всеми обязательными", _p),
                          ("req_full_top5_confirmed", "… и с подтверждённым грейдом", _p),
                          ("confirmed_any", "есть кандидат с подтверждённым грейдом", _p),
                          ("confirmed_exact", "… в точной категории", _p),
                          ("confirmed_right_direction", "… в направлении вакансии", _p)):
            lines.append(f"| {t} | {f(ko[key])} | {f(k[key])} | {f(oo[key])} | {f(o[key])} |")
    lines += ["", "## По направлениям", "",
              "| Направление | n | В каталоге | Разбор отнёс к | Направление верно | Грейд верно | Подтверждённые кандидаты | В направлении вакансии | Покрытие (лучший из 5) | Все обязательные в пятёрке |",
              "|---|---:|---|---|---|---|---|---|---|---|"]
    for d, x in r["directions"].items():
        pd = ", ".join(f"{a} {b}" for a, b in list(x["parsed_direction"].items())[:3])
        lines.append(f"| {x['title']} | {x['n']} | {'да' if x['in_catalog'] else 'нет (новое)'} | {pd} | {_p(x['direction_ok'])} | "
                     f"{_p(x['grade_ok'])} | {_p(x['confirmed_any'])} | {_p(x['confirmed_right_direction'])} | "
                     f"{_m(x['req_coverage_best_top5'])} | {_p(x['req_full_top5'])} |")
    if r.get("w1"):
        w = r["w1"]
        lines += ["", "## Что изменилось (W1, 19.10): по шагам", "", w["summary"], "",
                  "| Шаг | Направлений в каталоге | Подтверждённый кандидат в направлении вакансии (все 9) | "
                  "Покрытие обязательных у лучшего из 5 (все 9) | Направление разобрано верно |", "|---|---|---|---|---|"]
        for row in w["rows"]:
            lines.append(f"| {row['title']} | {row['dirs']} | {_p(row['confirmed_right_direction'])} | "
                         f"{_m(row['req_coverage_best_top5'])} | {_p(row['direction_ok']) if row.get('direction_ok') else '—'} |")
        lines += ["", *[f"* {x}" for x in w.get("caveats", [])]]
    new = [x for x in r["directions"].values() if not x["in_catalog"]]
    if new:
        lines += ["", "**Новые направления.** Пока их нет в каталоге (флаг каталога выключен), разбор относит такие вакансии к "
                  "ближайшему направлению, а подборка ищет кандидатов там — это и есть ошибка, которую исправляет расширение "
                  "каталога; после него прогон повторить той же командой."]
    lines += ["", "## Ошибки разбора", "", "По полям: " + ", ".join(f"{a} — {b}" for a, b in r["errors_by_field"].items()) + ".",
              "Первые 80 (номер вакансии → поле, ожидалось, получено) — `backend/app/modules/validation/data/hh_match.json`.",
              "Чаще всего пропущенные навыки из «Ключевых навыков»: " + "; ".join(
                  f"{x['title']}: " + ", ".join(f"{s['tag']} ({s['n']})" for s in x["missed_key_skills_top"][:3])
                  for x in r["directions"].values() if x["missed_key_skills_top"]) + ".", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--per", type=int, default=12, help="вакансий на направление × грейд")
    sub.add_parser("demand")
    sub.add_parser("market")
    sub.add_parser("skills")
    m = sub.add_parser("match")
    m.add_argument("--limit", type=int, default=10)
    sub.add_parser("render", help="только HH_MATCH.md из hh_match.json")
    a = ap.parse_args()
    {"collect": lambda: collect(a.per), "demand": demand, "market": market_snapshot, "skills": skills,
     "match": lambda: match(a.limit),
     "render": lambda: MD_MATCH.write_text(render_match(json.loads(OUT_MATCH.read_text(encoding="utf-8"))),
                                           encoding="utf-8")}[a.cmd]()


if __name__ == "__main__":
    main()
