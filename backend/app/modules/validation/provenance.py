"""Ф6 (Н7, Н8): честные подписи /validation и экрана старта теста из одного источника — без пересчёта чисел.

- Банк сейчас — манифест синхронизации банка (assessment_bank/BANK_SYNC.json): число семейств, hash, коммит, дата.
- Отчёт симуляции (data/report.json, ``make validate``) — его дата, банк, на котором он посчитан, и совпадает ли
  этот банк с текущим. Если не совпадает, числа отчёта — исторические и подписываются датой, а не «сейчас».
- Калибровка параметров — на панели МОДЕЛЕЙ (не людей): сколько семейств из текущего банка она покрывает.
- Длина теста — из конфигурации и итогов симуляции того же отчёта (синтетические кандидаты, модель ответов);
  время симуляции на людей не переносится: людям показываются только лимиты (минуты) и доля дотестирования в модели.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.modules.assessment.bank_engine import bank_manifest
from app.modules.validation.signature import git_commit


def provenance(report: dict) -> dict:
    m = bank_manifest()
    rb = report.get("bank") or {}
    cal = report.get("calibration") or {}
    now_n = m.get("n_families")
    same = bool(m.get("content_hash")) and m.get("content_hash") == rb.get("content_hash")
    return {
        "bank_now": {"n_families": now_n, "content_hash": m.get("content_hash"), "commit": m.get("commit"),
                     "synced_at": m.get("synced_at")},
        "report": {"generated_at": report.get("generated_at"), "bank_n_families": rb.get("n_families"),
                   "bank_hash": rb.get("content_hash"), "bank_commit": rb.get("commit"),
                   "bank_synced_at": rb.get("synced_at"), "same_bank": same,
                   "n_per_direction": report.get("n_per_direction")},
        "calibration": {"source": "model_panel", "status": cal.get("status"), "panel": cal.get("panel"),
                        "n_families": cal.get("n_families"), "of_families": now_n, "humans": False,
                        "used_in_decision": False},
        "code_commit": git_commit(),
        "stamp": stamp("report", report), "demo": stamp("demo", report),  # Я8: строка происхождения блоков отчёта
    }


def length_info(report: dict) -> dict:
    """Длина теста для экрана старта: лимиты конфигурации + среднее и доля дотестирования в симуляции отчёта."""
    sim = report.get("simulation") or {}
    cfg, mean = sim.get("config") or {}, sim.get("mean") or {}
    if not cfg or report.get("missing"):
        return {"missing": True}
    return {
        "min_items": cfg.get("min_items"), "max_items": cfg.get("max_items"), "max_minutes": cfg.get("max_minutes"),
        "ext_items": cfg.get("ext_items"), "ext_minutes": cfg.get("ext_minutes"),
        "sim_mean_items": mean.get("mean_items"), "sim_extension_share": mean.get("extension_share"),
        "sim_n_per_direction": report.get("n_per_direction"), "sim_directions": len(sim.get("directions") or {}),
        "generated_at": report.get("generated_at"),
        "world": "симуляция на синтетических кандидатах (модель ответов), не замер на людях",
    }


# ---------------------------------------------------------------------------------------------------------------
# Я8: происхождение каждого числа /validation и /criteria — одна строка «синтетика / модель / люди · дата ·
# SHA алгоритма · банк · команда воспроизведения» из JSON расчёта (не текстом на странице). Снимок «текущий»,
# если расчёт сделан на банке, который сейчас в продукте; иначе — «исторический» (с датой), чтобы числа разных
# снимков не читались как одно «текущее». Пересчёт на итоговой голове сам сводит их в один снимок.
DATA = Path(__file__).resolve().parent / "data"
KINDS = {"synthetic": "синтетика", "model": "модель, не люди", "people": "люди", "mixed": "модель и люди",
         "rules": "правила на демо-данных", "live": "живые данные стенда"}
# источник → файл расчёта, чем пересчитать, кто «размечал», какие блоки /validation он кормит
SOURCES: dict[str, dict] = {
    "path": {"file": "path_retest.json", "command": "make path-retest", "kind": "synthetic",
             "title": "Повтор всего пути, точность к истине, D и r_pb", "sections": ["headline", "path-retest"]},
    "bench": {"file": "matching_bench.json", "command": "make bench", "kind": "synthetic",
              "title": "Бенчмарк подбора со скрытой истиной, абляции", "sections": ["headline", "bench", "ablations"]},
    "attempts": {"file": "attempts_repeat.json", "command": "python -m app.modules.validation.attempts_repeat",
                 "kind": "synthetic", "title": "Повторы заданий между попытками", "sections": ["retest-repeats"]},
    "report": {"file": "report.json", "command": "make validate", "kind": "synthetic",
               "title": "Симуляция теста: точность, повтор, частота показа, утечка",
               "sections": ["retest", "test", "others", "exposure", "leak"]},
    "demo": {"file": "report.json", "command": "make validate", "kind": "rules",
             "title": "Подбор на демо-данных (метки правилами, циркулярно)", "sections": ["matching"]},
    "stability": {"file": "junior_stability.json", "command": "make stability", "kind": "synthetic",
                  "title": "Junior у порога", "sections": ["junior"]},
    "intern": {"file": "intern_cut.json", "command": "make intern-cut", "kind": "synthetic",
               "title": "Порог Стажёра", "sections": ["intern"]},
    "grader": {"file": "grader_check.json", "command": "python -m app.modules.validation.grader_check report",
               "kind": "model", "title": "Оценщик открытых ответов против модели-эталона", "sections": ["grader"]},
}
_cache: dict[str, tuple[float, dict | None]] = {}


def load(src: str) -> dict | None:
    """JSON расчёта источника (кэш по времени изменения файла)."""
    p = DATA / SOURCES[src]["file"]
    try:
        mt = p.stat().st_mtime
    except OSError:
        return None
    hit = _cache.get(p.name)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = None
    _cache[p.name] = (mt, d)
    return d


def _known(v) -> str | None:
    return v if v and v not in ("unknown", "не записан") else None


def stamp(src: str, d: dict | None = None) -> dict:
    """Строка происхождения числа: вид данных, дата расчёта, SHA кода расчёта, банк (и текущий ли он), команда."""
    spec = SOURCES[src]
    d = load(src) if d is None else d
    out = {"src": src, "kind": spec["kind"], "kind_label": KINDS[spec["kind"]], "title": spec["title"],
           "command": spec["command"], "sections": spec["sections"], "date": None, "commit": None, "bank": None,
           "bank_families": None, "bank_current": None, "snapshot": "missing"}
    if not d or d.get("missing"):
        return out
    m = bank_manifest()
    sig = d.get("signature") or {}
    if sig:
        out.update(date=sig.get("generated_at"), commit=_known(sig.get("commit")), bank=sig.get("bank"),
                   command=sig.get("command") or spec["command"])
    else:  # make validate / intern-cut / grader_check подписи не пишут: дата — из отчёта, коммит честно не записан
        b = d.get("bank") or {}
        out.update(date=d.get("generated_at") or d.get("date"), bank=b.get("content_hash"),
                   bank_families=b.get("n_families"))
    if out["bank"] and out["bank"] == m.get("content_hash"):
        out["bank_families"] = m.get("n_families")
    elif src == "path":
        out["bank_families"] = (d.get("config") or {}).get("n_families")
    if out["bank"]:
        out["bank_current"] = out["bank"] == m.get("content_hash")
        out["snapshot"] = "current" if out["bank_current"] else "historical"
    else:  # банк не записан (порог Стажёра) или расчёт от банка не зависит (оценщик ответов на наборе панели)
        out["snapshot"] = "no_bank" if spec["kind"] == "model" else "bank_unknown"
    return out


def experts_stamp(ex: dict | None) -> dict:
    """Разметка /validation#experts считается по базе при запросе: вид — кто размечал (модельная панель / люди)."""
    src = (ex or {}).get("source") or {}
    kind = "model" if (ex or {}).get("model_panel") else {"people": "people", "mixed": "mixed"}.get(src.get("kind"), "people")
    seen = [p.get("last_seen_at") for p in (ex or {}).get("panel") or [] if p.get("last_seen_at")]
    return {"src": "experts", "kind": kind, "kind_label": KINDS[kind], "title": src.get("title") or "разметки пока нет",
            "command": "GET /api/validation/report (пересчёт по базе при запросе)", "sections": ["experts"],
            "date": max(seen) if seen else None, "commit": git_commit(), "bank": None, "bank_families": None,
            "bank_current": None, "snapshot": "live" if src else "missing"}


def snapshots() -> dict:
    """GET /api/validation/provenance: банк и код сейчас + строка происхождения каждого расчёта /validation."""
    m = bank_manifest()
    rows = [stamp(s) for s in SOURCES]
    cur = [r for r in rows if r["snapshot"] == "current"]
    return {"bank_now": {"content_hash": m.get("content_hash"), "n_families": m.get("n_families"),
                         "commit": m.get("commit"), "synced_at": m.get("synced_at")},
            "code_commit": git_commit(), "kinds": KINDS, "sources": rows,
            "one_snapshot": all(r["snapshot"] in ("current", "no_bank") for r in rows),
            "current_commits": sorted({r["commit"] for r in cur if r["commit"]}),
            "how_to_read": ("Каждое число — из сохранённого расчёта. «Текущий снимок» — посчитан на банке, который "
                            "сейчас в продукте; «исторический» — на прошлом банке, его числа подписаны датой и "
                            "не смешиваются с текущими. Пересчёт: команда в строке.")}
