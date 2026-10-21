"""Индекс протоколов ФСП v2: записи привязаны к соревнованиям, проверены по ЕВСК, очищены.

Что меняется относительно index.json (v1):
* каждая запись привязана к соревнованию из ``evsk_data/events.json`` по файлу и странице; записи со
  страниц справок (судьи, подписи, списки субъектов) удаляются;
* удаляются тренеры, судьи и сотрудники сборной (роль из постраничного распознавания);
* дисциплина, ЕКП и даты берутся из реквизитов соревнования (в v1 у КФ-2026 стояла чужая дисциплина,
  у КР-2026 — одна дата на все этапы);
* КР-2026 СИБ: страницы 1–6 распознаны заново (блоки команд + линии таблицы), в v1 было 30 из 244;
* дубли турнирной таблицы КР-2026 (алгоритмическое) с протоколом того же соревнования убираются;
* добавлены поля: event_id, event_status, level, age_group, team_event, person, rank_listed, evsk_*.

Запуск на сервере (stdlib, без зависимостей):
  FSP_EVSK_DATA_DIR=<evsk_data> python3 build_index_v2.py <каталог fsp_protocols> <каталог с evsk.py и normalize.py>
Результат: index_v2.json (600) и index_v2_report.json (без ПДн) в каталоге fsp_protocols.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

base = Path(sys.argv[1])
code = Path(sys.argv[2])
OUT_NAME = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else "index_v3.json"
WRITE_W1 = "--w1" in sys.argv
APP_UID = 10001  # пользователь api в контейнере — файл индекса должен быть его (600)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


evsk = _load("evsk", code / "evsk.py")
norm = _load("normalize", code / "normalize.py")

STAFF_ROLES_OK = {"спортсмен", "команда", ""}
SPORT_RANKS = {"МСМК", "МС", "КМС", "I", "II", "III", "Iю", "IIю", "IIIю"}
NO_PERSON_DOCS = {"txbuswvkginckkbtbwtkata1wbfukqda.pdf", "9uxtofnr07t1n3lha1o0ku1anbqndqe1.pdf",
                  "f4ikw0r1e2qwmvt3usudy5ve81r3ykrf.pdf"}  # протоколы только с названиями команд
REBUILT = {"e6rp6ekcljtfofzw99bao13a8mpav8i9.pdf": ("kr_2026_sib_otbor", range(1, 7))}
TABLE_DUP = "f0gja1njckgfwu6heobl1o3z4021wlpg.pdf"
DOC_BY_FILE = {}

v1 = json.loads((base / "index.json").read_text(encoding="utf-8"))
for s in v1["sources"]:
    DOC_BY_FILE[s["pdf_url"].rsplit("/", 1)[-1]] = s
events_doc = json.loads((Path(os.environ["FSP_EVSK_DATA_DIR"]) / "events.json").read_text(encoding="utf-8"))
events = events_doc["events"]
page_map = events_doc["page_map"]


def seg_for(fn: str, page: int | None) -> dict | None:
    for s in page_map.get(fn, []):
        a, b = s["pages"]
        if page is not None and a <= int(page) <= b and s["page_type"] != "protocol":
            return s
    for s in page_map.get(fn, []):
        a, b = s["pages"]
        if page is not None and a <= int(page) <= b:
            return s
    return None


cache = {}
for root in ("work/cache", "work/cache_v2"):
    for f in (base / root).glob("*/pages_json/*.json"):
        doc_id = f.parts[-3]
        page = int(f.stem.split("_")[-1])
        cache[(doc_id, page)] = json.loads(f.read_text(encoding="utf-8"))


def role_of(doc_id: str, page: int, fio_norm: str | None) -> str | None:
    d = cache.get((doc_id, page))
    if not d or not fio_norm:
        return None
    for r in d.get("rows") or []:
        if r.get("fio") and norm.normalize_fio(r["fio"]) == fio_norm:
            return (r.get("role") or "").strip()
    return None


removed = collections.Counter()
out: list[dict] = []


def enrich(r: dict, fn: str) -> dict | None:
    seg = seg_for(fn, r.get("page"))
    if seg is None:
        removed["страница вне размеченных соревнований"] += 1
        return None
    if seg["page_type"] != "protocol":
        removed["страница справки (судьи, подписи, субъекты)"] += 1
        return None
    ev = events[seg["event_id"]]
    r = dict(r)
    r["event_id"] = seg["event_id"]
    r["event_title"] = ev["title"]
    r["ekp_no"] = ev.get("ekp_no")
    r["date"] = ev.get("date_start")
    r["date_end"] = ev.get("date_end")
    if ev.get("discipline"):
        r["discipline"] = ev["discipline"]
    r["event_status"] = ev.get("evsk_status")
    r["stage"] = ev.get("stage")
    r["age_group"] = ev.get("age_group")
    r["team_event"] = ev.get("team_event")
    if ev.get("fo"):
        r["fo"] = ev["fo"]
    raw = (r.get("rank") or "").strip()
    r["rank_listed"] = raw if raw in SPORT_RANKS else None
    if raw and raw not in SPORT_RANKS:
        r["rank_raw"] = raw
    r["rank"] = r["rank_listed"]
    fio = r.get("fio_norm") or ""
    r["person"] = fn not in NO_PERSON_DOCS and len(fio.split()) >= 2
    if r["person"] and ev.get("evsk_status") is not None:
        e = evsk.evsk_rank_for(r, ev)
        r["evsk_rank"] = e["rank"]
        r["evsk_status"] = e["status"]
        r["evsk_fulfilled"] = e["fulfilled"]
        r["evsk_pending"] = e["pending"]
        b = e.get("basis")
        r["evsk_basis_short"] = (f"Приложение № 24 к приказу Минспорта № 450, стр. {b['page']}: {b['row']}, {b['column']} — места {b['places']}"
                                 if b else None)
    else:
        r["evsk_rank"] = None
        r["evsk_status"] = "no_norm" if ev.get("evsk_status") is None else None
        r["evsk_fulfilled"] = False
    return r


for r in v1["records"]:
    fn = r["pdf_url"].rsplit("/", 1)[-1]
    if fn not in page_map:
        removed["документ — не протокол (справка о судьях)"] += 1
        continue
    if fn in REBUILT and r.get("page") in REBUILT[fn][1]:
        removed["заменено повторным распознаванием (КР-2026 СИБ, стр. 1–6)"] += 1
        continue
    doc_id = DOC_BY_FILE.get(fn, {}).get("doc_id")
    role = role_of(doc_id, r.get("page"), r.get("fio_norm")) if doc_id else None
    if role is not None and role.lower() not in STAFF_ROLES_OK:
        removed[f"не спортсмен: {role.lower()[:40]}"] += 1
        continue
    if (r.get("rank") or "").strip() in {"ВК", "1К", "2К", "3К"}:
        removed["судья (судейская категория вместо разряда)"] += 1
        continue
    e = enrich(r, fn)
    if e:
        out.append(e)

# КР-2026 СИБ: новые записи со страниц 1–6
for fn, (doc_id, pages) in REBUILT.items():
    src = DOC_BY_FILE[fn]
    for p in pages:
        d = cache.get((doc_id, p)) or {}
        for row in d.get("rows") or []:
            fio_norm = norm.normalize_fio(row.get("fio"))
            if not fio_norm:
                continue
            bdate, byear = norm.extract_birth_date(row.get("birth_date"))
            rec = {"key_hash": norm.compute_key_hash(fio_norm, byear), "fio_hash": norm.compute_fio_hash(fio_norm),
                   "fio_norm": fio_norm, "birth_date": bdate or byear, "discipline": d.get("discipline"),
                   "place": row.get("place"), "rank": None, "team": row.get("team"), "region": row.get("region"),
                   "pdf_url": src["pdf_url"], "page": p, "recognized": "v2_team_blocks"}
            e = enrich(rec, fn)
            if e:
                out.append(e)

# турнирная таблица КР-2026 (алгоритмическое) — то же соревнование, что и протокол; источник истины —
# протокол. Записи таблицы не берём: совпадающие — дубли, несовпадающие — варианты написания ФИО при
# распознавании (раздували бы число спортсменов).
final = []
for r in out:
    if r["pdf_url"].endswith(TABLE_DUP):
        removed["турнирная таблица КР-2026 (дублирует протокол того же соревнования)"] += 1
        continue
    final.append(r)

# index_w1.json — минимальная очистка для выкладки волны 1: записи v1 без судей, тренеров, сотрудников
# сборной и строк со страниц справок; поля как в v1 (rank очищен, исходное — rank_raw)
w1_keep = []
for r in v1["records"]:
    fn = r["pdf_url"].rsplit("/", 1)[-1]
    if fn not in page_map:
        continue
    sg = seg_for(fn, r.get("page"))
    if sg is None or sg["page_type"] != "protocol":
        continue
    doc_id = DOC_BY_FILE.get(fn, {}).get("doc_id")
    role = role_of(doc_id, r.get("page"), r.get("fio_norm")) if doc_id else None
    if role is not None and role.lower() not in STAFF_ROLES_OK:
        continue
    raw = (r.get("rank") or "").strip()
    if raw in {"ВК", "1К", "2К", "3К"}:
        continue
    rr = dict(r)
    if raw and raw not in SPORT_RANKS:
        rr["rank_raw"], rr["rank"] = raw, None
    w1_keep.append(rr)
w1 = dict(v1)
w1["records"] = w1_keep
w1["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
w1["schema_version"] = "1.0+w1clean2"
w1["stats"] = dict(v1["stats"], total_records=len(w1_keep), unique_athletes_count=len({r.get("fio_hash") for r in w1_keep}))
if WRITE_W1:
    t1 = base / "index_w1.json"
    (t1.with_suffix(".tmp")).write_text(json.dumps(w1, ensure_ascii=False), encoding="utf-8")
    os.chmod(t1.with_suffix(".tmp"), 0o600)
    t1.with_suffix(".tmp").replace(t1)
    print("index_w1.json:", len(w1_keep), "записей,", w1["stats"]["unique_athletes_count"], "уникальных ФИО")

persons = [r for r in final if r["person"]]
st = collections.Counter(r.get("evsk_status") for r in persons)
ranks = collections.Counter(r.get("evsk_rank") for r in persons if r.get("evsk_status") in ("fulfilled", "needs_second_result"))
by_event = collections.Counter(r["event_id"] for r in final)
best: dict[str, dict] = {}
order = {"МС": 0, "КМС": 1, "I": 2, "II": 3, "III": 4}
for r in persons:
    if r.get("evsk_status") == "fulfilled" and r.get("evsk_rank"):
        k = r["fio_hash"]
        if k not in best or order.get(r["evsk_rank"], 9) < order.get(best[k]["evsk_rank"], 9):
            best[k] = r

sources = []
for fn, segs in page_map.items():
    s = DOC_BY_FILE.get(fn)
    evs = sorted({x["event_id"] for x in segs if x["page_type"] == "protocol"})
    sources.append({"filename": fn, "doc_id": (s or {}).get("doc_id"), "pdf_url": (s or {}).get("pdf_url") or events_doc["sources"].get(fn, {}).get("url"),
                    "sha256": events_doc["sources"].get(fn, {}).get("sha256"), "events": evs,
                    "records_count": sum(1 for r in final if r["pdf_url"].rsplit("/", 1)[-1] == fn)})

now = datetime.now(timezone.utc).isoformat(timespec="seconds")
stats = {
    "documents_count": len(sources),
    "events_count": len({r["event_id"] for r in final}),
    "total_records": len(final),
    "person_records": len(persons),
    "team_only_records": len(final) - len(persons),
    "unique_athletes_count": len({r["fio_hash"] for r in persons}),
    "by_event": dict(by_event),
    "evsk_status_counts": dict(st),
    "evsk_rank_counts_fulfilled_or_second": {k: v for k, v in ranks.items() if k},
    "athletes_with_fulfilled_norm": len(best),
    "athletes_with_fulfilled_norm_by_rank": dict(collections.Counter(r["evsk_rank"] for r in best.values())),
}
idx = dict(v1)
idx.update({"schema_version": "2.0", "generated_at": now, "stats": stats, "sources": sources, "records": final,
            "events_version": events_doc.get("version")})
target = base / OUT_NAME
if target.exists() and "--force" not in sys.argv:
    sys.exit(f"{target} уже существует: выложенные версии индекса не перезаписываются (новое имя или --force)")
tmp = target.with_suffix(".tmp")
tmp.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
os.chmod(tmp, 0o600)
try:
    os.chown(tmp, APP_UID, APP_UID)
except PermissionError:
    pass
tmp.replace(target)
report = {"generated_at": now, "input_records_v1": len(v1["records"]), "output_records": len(final),
          "removed_by_reason": dict(removed), "stats": stats}
rep_path = base / (OUT_NAME.replace(".json", "") + "_report.json")
rep_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
os.chmod(rep_path, 0o600)
print(json.dumps(report, ensure_ascii=False, indent=1))
