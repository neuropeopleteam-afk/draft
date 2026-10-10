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
        "exposure_k": {**stamp("exposure_k"), "note": config_note("exposure_k")},  # Я8: K, которые читает движок
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
         "rules": "правила на демо-данных", "live": "живые данные стенда", "tests": "автотесты",
         "doc": "документация", "measured": "замер нагрузки", "yours": "ваши данные"}
# источник → файл расчёта, чем пересчитать, кто «размечал», какие блоки /validation он кормит
SOURCES: dict[str, dict] = {
    "path": {"file": "path_retest.json", "command": "make path-retest", "kind": "synthetic",
             "title": "Повтор всего пути, точность к истине, D и r_pb", "sections": ["headline", "path-retest", "discrimination"]},
    "bench": {"file": "matching_bench.json", "command": "make bench", "kind": "synthetic",
              "title": "Бенчмарк подбора со скрытой истиной, абляции", "sections": ["headline", "bench", "ablations"]},
    "attempts": {"file": "attempts_repeat.json", "command": "python -m app.modules.validation.attempts_repeat",
                 "kind": "synthetic", "title": "Повторы заданий между попытками", "sections": ["retest-repeats"]},
    "report": {"file": "report.json", "command": "make validate", "kind": "synthetic",
               "title": "Симуляция теста: точность, повтор, частота показа, утечка",
               "sections": ["retest", "test", "competitors", "exposure", "leak", "calibration"]},
    "demo": {"file": "report.json", "command": "make validate", "kind": "rules",
             "title": "Подбор на демо-данных (метки правилами, циркулярно)", "sections": ["matching"]},
    "stability": {"file": "junior_stability.json", "command": "make stability", "kind": "synthetic",
                  "title": "Junior у порога", "sections": ["junior"]},
    "intern": {"file": "intern_cut.json", "command": "make intern-cut", "kind": "synthetic",
               "title": "Порог Стажёра", "sections": ["intern"]},
    "grader": {"file": "grader_check.json", "command": "python -m app.modules.validation.grader_check report",
               "kind": "model", "title": "Оценщик открытых ответов против модели-эталона", "sections": ["grader"]},
    # K Sympson — Hetter, которые читает движок теста (assessment/exposure_k.json): дата и банк калибровки
    "exposure_k": {"file": "exposure_k.json", "dir": "assessment", "command": "make validate (tools/calibrate_exposure.py)",
                   "kind": "synthetic", "title": "Коэффициенты K Sympson — Hetter (движок теста)",
                   "sections": ["exposure"], "role": "config"},  # настройка движка, а не число страницы
}
_cache: dict[str, tuple[float, dict | None]] = {}


def load(src: str) -> dict | None:
    """JSON расчёта источника (кэш по времени изменения файла)."""
    spec = SOURCES[src]
    p = (DATA.parents[1] / spec["dir"] if spec.get("dir") else DATA) / spec["file"]
    try:
        mt = p.stat().st_mtime
    except OSError:
        return None
    hit = _cache.get(str(p))
    if hit and hit[0] == mt:
        return hit[1]
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = None
    _cache[str(p)] = (mt, d)
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


def config_note(src: str) -> str | None:
    """Пояснение к настройке движка (K Sympson — Hetter): на каком банке откалибровано и что с новыми семействами."""
    if src != "exposure_k":
        return None
    st, m = stamp(src), bank_manifest()
    if st["snapshot"] == "missing":
        return "Файла K нет — частота показа не ограничивается (K = 1)."
    if st["bank_current"]:
        return "K откалиброваны на банке, который сейчас в продукте."
    d = str(st.get("date") or "")
    when = f"{d[8:10]}.{d[5:7]}.{d[:4]}" if d else "без даты"
    return (f"K откалиброваны {when} на банке {st.get('bank_families') or '—'} семейств (сейчас {m.get('n_families')}): "
            "у семейств, добавленных позже, K = 1 — частота их показа не ограничена. Числа страницы посчитаны с этими "
            "K — так движок работает сейчас; пересчёт K (make validate) меняет выбор заданий в продукте — решение "
            "штаба, сравнение — в docs/validation/EXPOSURE_K_RECALC.md.")


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
    rows = [stamp(s) for s in SOURCES if SOURCES[s].get("role") != "config"]
    config = [{**stamp(s), "note": config_note(s)} for s in SOURCES if SOURCES[s].get("role") == "config"]
    cur = [r for r in rows if r["snapshot"] == "current"]
    return {"bank_now": {"content_hash": m.get("content_hash"), "n_families": m.get("n_families"),
                         "commit": m.get("commit"), "synced_at": m.get("synced_at")},
            "code_commit": git_commit(), "kinds": KINDS, "sources": rows, "config": config,
            "one_snapshot": all(r["snapshot"] in ("current", "no_bank") for r in rows),
            "current_commits": sorted({r["commit"] for r in cur if r["commit"]}),
            "how_to_read": ("Каждое число — из сохранённого расчёта. «Текущий снимок» — посчитан на банке, который "
                            "сейчас в продукте; «исторический» — на прошлом банке, его числа подписаны датой и "
                            "не смешиваются с текущими. Пересчёт: команда в строке.")}


# ---------------------------------------------------------------------------------------------- /criteria (п. 5)
# Доказательство /criteria без числа: ссылка на блок /validation — происхождение блока; живые данные стенда (SUS,
# «красная кнопка», свой закрытый набор) — «по базе при запросе»; документ репозитория — автотесты / описание /
# замер, по коду этой версии (коммит), с командой воспроизведения.
LIVE = {
    "/sus": ("Анкета SUS — ответы на этом стенде", "живые анкеты, GET /api/sus/summary"),
    "/validation#red-button": ("Атака на живом движке и демо-данных стенда", "кнопка на /validation#red-button"),
    "/validation#closed-set": ("Ваш закрытый набор — считается при запросе", "загрузка набора на /validation#closed-set",
                               "yours"),
    "/validation#self-check": ("Синтетический кандидат на движке продукта", "кнопка на /validation#self-check"),
}
DOCS = {  # документ → вид доказательства и команда воспроизведения
    "docs/testing.md": ("tests", "make test-local · make e2e"),
    "docs/ATS.md": ("tests", "pytest tests/test_ats_providers.py tests/test_ats_stages.py"),
    "docs/LOAD_TEST.md": ("measured", "Locust, сценарий — docs/LOAD_TEST.md"),
    "README.md": ("doc", "make up"),
    "docs/CRITERIA.md": ("doc", "make criteria-doc"),
}


def proof_stamp(proof: dict) -> dict | None:
    """Строка происхождения доказательства /criteria — той же формы, что stamp() у чисел /validation."""
    kind = proof.get("kind")
    if kind == "metric" and proof.get("src") in SOURCES:
        return stamp(proof["src"])
    if kind == "doc":
        k, cmd = DOCS.get(proof.get("path") or "", ("doc", None))
        return {"src": "doc", "kind": k, "kind_label": KINDS[k], "title": proof.get("label"), "command": cmd,
                "sections": [], "date": None, "commit": git_commit(), "bank": None, "bank_families": None,
                "bank_current": None, "snapshot": "code"}
    to = proof.get("anchor") or ""
    if to in LIVE or kind == "sus":
        title, cmd, *k = LIVE.get(to, LIVE["/sus"])
        k = k[0] if k else "live"
        return {"src": "live", "kind": k, "kind_label": KINDS[k], "title": title, "command": cmd,
                "sections": [], "date": None, "commit": git_commit(), "bank": None, "bank_families": None,
                "bank_current": None, "snapshot": "live"}
    anchor = to.split("#", 1)[1] if "#" in to else None
    src = next((k for k, v in SOURCES.items() if anchor and anchor in v["sections"]), None)
    return stamp(src) if src else None


SNAPSHOT_TEXT = {"current": "текущий снимок", "historical": "исторический снимок", "no_bank": "от банка не зависит",
                 "bank_unknown": "банк не записан", "live": "по базе при запросе", "missing": "не посчитано",
                 "code": "по коду этой версии"}


def stamp_text(pv: dict | None, *, with_code_commit: bool = False) -> str:
    """Строка происхождения текстом (docs/CRITERIA.md, docs/validation/PROVENANCE.md): вид · снимок · дата ·
    алгоритм · банк · команда. Коммит кода «этой версии» (документы, живые данные) — только по запросу: в
    сгенерированном документе он менялся бы с каждым коммитом."""
    if not pv:
        return ""
    parts = [pv.get("kind_label"), SNAPSHOT_TEXT.get(pv.get("snapshot") or "", pv.get("snapshot"))]
    if pv.get("date"):
        d = str(pv["date"])
        parts.append(f"{d[8:10]}.{d[5:7]}.{d[:4]}")
    if pv.get("commit") and (pv.get("snapshot") not in ("code", "live") or with_code_commit):
        parts.append(f"алгоритм `{pv['commit']}`")
    elif pv.get("snapshot") not in ("code", "live"):
        parts.append("коммит не записан")
    if pv.get("bank"):
        n = f" ({pv['bank_families']} семейств)" if pv.get("bank_families") else ""
        parts.append(f"банк `{str(pv['bank'])[:8]}`{n}")
    if pv.get("command"):
        parts.append(f"`{pv['command']}`")
    return " · ".join(x for x in parts if x)


# ------------------------------------------------------------------------------- docs/validation/PROVENANCE.md
def markdown() -> str:
    """docs/validation/PROVENANCE.md — таблица снимков из того же источника, что GET /api/validation/provenance
    (без коммита кода «этой версии»: он менялся бы с каждым коммитом). Прозу документа см. PROSE ниже."""
    s = snapshots()
    b = s["bank_now"]
    out = [PROSE_HEAD.strip(), "",
           f"Банк в продукте сейчас: `{(b.get('content_hash') or '')[:16]}` — {b.get('n_families')} семейств "
           f"(коммит банка `{b.get('commit')}`, синхронизация {str(b.get('synced_at') or '')[:10]}). "
           f"Один снимок: **{'да' if s['one_snapshot'] else 'нет'}**"
           + (f" (расчёты на коммитах {', '.join('`' + c + '`' for c in s['current_commits'])})."
              if s["current_commits"] else "."), "",
           "| Расчёт | Блоки /validation | Строка происхождения |", "|---|---|---|"]
    for r in s["sources"] + s["config"]:
        out.append(f"| {r['title']} (`{SOURCES[r['src']]['file']}`) | {', '.join('#' + x for x in r['sections'])} | "
                   f"{stamp_text(r)} |")
    for r in s["config"]:
        out += ["", f"**{r['title']}.** {r['note']}"]
    out += ["", PROSE_TAIL.strip(), ""]
    return "\n".join(out)


PROSE_HEAD = """
# Происхождение чисел /validation и /criteria

Сгенерировано `python -m app.modules.validation.provenance --md ../docs/validation/PROVENANCE.md` из того же
источника, что `GET /api/validation/provenance` и строки происхождения на страницах. Не править руками.

У каждого ключевого числа `/validation` и у каждого доказательства `/criteria` — строка происхождения:
**вид данных · снимок · дата расчёта · SHA алгоритма · банк · команда воспроизведения**. Всё берётся из JSON
расчёта (подпись `signature`: коммит кода, на котором посчитано, hash банка, seed, hash конфигурации), а не
текстом страницы.

- Вид данных: «синтетика» (синтетические кандидаты, модель ответов 2PL, истина заданий = предкалибровка + ошибка
  эксперта), «модель, не люди» (модельная панель Claude Fable 5.1 в трёх ролях, оценщик против модели-эталона),
  «правила на демо-данных» (метки релевантности правилами — циркулярно), «люди», «живые данные стенда»,
  «автотесты», «документация», «замер нагрузки», «ваши данные».
- Снимок: «текущий» — расчёт сделан на банке, который сейчас в продукте; «исторический» — на прошлом банке, его
  числа подписаны датой и не смешиваются с текущими; «по базе при запросе» — считается живьём; «по коду этой
  версии» — автотесты и описания репозитория.
"""

PROSE_TAIL = """
## Модельная панель — не люди

Блок экспертов на `/validation#experts` озаглавлен «Модельная панель (Claude Fable 5.1 в трёх ролях) — не люди».
κ между прогонами одной модели — согласие коррелированных прогонов, а не межэкспертная надёжность людей и не
точность разметки.

## Повтор ≠ точность

κ повтора всего пути показывает повторяемость. Рядом с ним на первом экране и в `#path-retest` — точность к
синтетической истине, доля «выше истинного», «ниже истинного» и «без категории» из того же `path_retest.json`:
правило подтверждения грейда при P ≥ 0,8 осторожно против завышения, поэтому занижение заметно; маршрут
восстановления — дотестирование у порога и вторая попытка на новых вариантах другого субпула (`TEST_RETEST.md`).

## Интеграции: метки происхождения

ФСП, ФНС (ЕГРЮЛ) и ATS подписаны метками «модельные данные» / «заглушка по спецификации» / «реальный запрос» /
«не проверено» (`backend/app/core/origin.py`, `frontend/src/components/Origin.tsx`; правила — в
`docs/FSP_INTEGRATION.md` и `docs/ATS.md`).

## Как пересчитать в один снимок

`make validate` (K Sympson — Hetter, отчёт симуляции, подбор на демо-данных), `make path-retest`, `make bench`,
`make stability`, `make intern-cut`, `python -m app.modules.validation.attempts_repeat`, затем `make criteria-doc` и
эта команда. Когда все расчёты сделаны на банке продукта, строка «Один снимок» — «да», а исторических снимков нет.
"""


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="docs/validation/PROVENANCE.md из реестра расчётов /validation")
    ap.add_argument("--md", type=Path, help="записать файл (без аргумента — печать)")
    a = ap.parse_args()
    text = markdown()
    if a.md:
        a.md.write_text(text, encoding="utf-8")
        print(f"записано: {a.md}")
    else:
        print(text)


if __name__ == "__main__":
    main()
