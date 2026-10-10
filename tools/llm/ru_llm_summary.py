"""Сводка замера «только российская модель» (tools/llm/ru_llm_bench.py) → backend/app/modules/validation/data/ru_llm.json
(одна копия: её отдаёт GET /api/validation/ru-llm; docs/ в образ api не входит) и таблица раздела 11 docs/LLM.md.

Из рабочего каталога прогона (--dir): <модель>/{needs_delta,needs_full,needs_jury,resume,grade}.json и rules/*.json.
В сводку попадают только метрики (без текстов ответов моделей и без ключей). Модель без прогона — status «pending»
с причиной; прежний замер YandexGPT 5.1 (08.10, полный разбор на коде c1c248e) — отдельной строкой «ref_0810».
"""
from __future__ import annotations

import json
from pathlib import Path
import statistics as st
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "realdata"))

DATA = ROOT / "backend/app/modules/validation/data/ru_llm.json"
SONNET = "openrouter=anthropic/claude-sonnet-5.5"
YANDEX = "yandex=yandexgpt-5.1/latest"
MODELS = [
    {"key": "sonnet", "spec": SONNET, "label": "Claude Sonnet 5.5", "where": "OpenRouter (зарубежный провайдер)",
     "role": "основная модель стенда"},
    {"key": "yandex", "spec": YANDEX, "label": "YandexGPT 5.1", "where": "Yandex AI Studio (РФ)",
     "role": "режим LLM_CHAIN=yandex; на стенде — запасная"},
    {"key": "rules", "spec": None, "label": "Правила и словари", "where": "наш сервер, без сети",
     "role": "последний рубеж у каждой функции"},
]
FORMAT_ERRORS = ("invalid_json", "invalid_reply", "empty", "schema_rejected")
USD_RUB = 85.42  # курс ЦБ РФ на 09.10.2026 (85,4173 ₽/$, cbr.ru) — для пересчёта цены OpenRouter в рубли
PRICE_RUB_PER_1K = {"yandexgpt-5.1": (0.8, 0.8), "yandexgpt": (1.2, 1.2)}

FUNCS = [
    {"key": "needs_delta", "func": "parse_need", "title": "Разбор потребности (путь продукта: словарь + дельта модели)",
     "set": "50 реальных вакансий (опубликованные тексты, docs/realdata/vacancies_50.json), silver-разметка — не экспертная",
     "metric": "F1 стека (модель + правила)"},
    {"key": "needs_full", "func": "parse_need", "title": "Разбор потребности, полный запрос (mode=full)",
     "set": "те же 50 вакансий", "metric": "F1 стека (модель + правила)"},
    {"key": "needs_jury", "func": "parse_need", "title": "Потребности «как у жюри»: сленг, английский стек",
     "set": "15 демо- и жюрийных текстов (tools/fastparse/bench.py), без разметки",
     "metric": "итоговые теги совпали с Sonnet, текстов"},
    {"key": "resume", "func": "resume", "title": "Разбор резюме (после вырезания ПДн)",
     "set": "20 синтетических резюме (docs/llm/resume_synth.json), разметка автора набора — модель",
     "metric": "F1 стека (модель + словари)"},
    {"key": "grade", "func": "grade, grade_second", "title": "Оценка развёрнутого ответа + вторая оценка спорных",
     "set": "набор оценщика: 29 заданий, 406 ответов (эталоны, ответы моделей, 116 атак); эталон — gpt-oss-120b, не эксперты",
     "metric": "MAE к эталону (ответы B), атаки прошли"},
]


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else None


def f1(p, r):
    return round(2 * p * r / (p + r), 4) if p and r else 0.0


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _calls(per_text: list[dict]) -> dict:
    """Доля ответов, отказы формата и сети, задержка p50/p95 (по принятым ответам), токены и цена."""
    called = [x for x in per_text if x.get("called")]
    ok = [x for x in called if x.get("ok")]
    fmt = [x for x in called if not x.get("ok") and x.get("error") in FORMAT_ERRORS]
    lat = [x["latency_ms"] / 1000 for x in ok if x.get("latency_ms") is not None]
    pt = sum(x.get("prompt_tokens") or 0 for x in called)
    ct = sum(x.get("completion_tokens") or 0 for x in called)
    cost = sum(x.get("cost_usd") or 0 for x in called)
    errors: dict[str, int] = {}
    for x in called:
        if not x.get("ok"):
            errors[x.get("error") or "?"] = errors.get(x.get("error") or "?", 0) + 1
    return {"n": len(per_text), "calls": len(called), "ok": len(ok), "format_fail": len(fmt),
            "transport_fail": len(called) - len(ok) - len(fmt), "errors": errors,
            "p50_s": round(pct(lat, 0.5), 2) if lat else None, "p95_s": round(pct(lat, 0.95), 2) if lat else None,
            "tokens": {"prompt": pt, "completion": ct}, "cost_usd": round(cost, 4) if cost else None}


def _price(model_key: str, c: dict, spec: str | None) -> dict:
    """Цена на 1000 вызовов: OpenRouter — фактическая (usage.cost), Yandex — токены × тариф AI Studio."""
    if not c.get("calls"):
        return {}
    if model_key == "yandex":
        name = (spec or "").split("=", 1)[-1].split("/")[0]
        pin, pout = PRICE_RUB_PER_1K.get(name, PRICE_RUB_PER_1K["yandexgpt-5.1"])
        rub = c["tokens"]["prompt"] / 1000 * pin + c["tokens"]["completion"] / 1000 * pout
        return {"rub_per_1k_calls": round(rub / c["calls"] * 1000, 1), "basis": f"токены × {pin} / {pout} ₽ за 1000"}
    if c.get("cost_usd"):
        usd = c["cost_usd"] / c["calls"] * 1000
        return {"usd_per_1k_calls": round(usd, 2), "rub_per_1k_calls": round(usd * USD_RUB, 1),
                "basis": f"usage.cost OpenRouter, {USD_RUB:g} ₽/$"}
    return {}


def _needs_quality(rows: list[dict], preds: list[dict]) -> dict:
    from benchmark import measure

    m = measure(rows, preds)
    p, r = m["stack_micro_precision"], m["stack_micro_recall"]
    fl = m["fields"]
    return {"stack_p": p, "stack_r": r, "stack_f1": f1(p, r), "tp_fp_fn": m["stack_tp_fp_fn"],
            "direction": fl["direction"]["correct"], "experience": fl["experience_years_min"]["correct"],
            "work_format": fl["work_format"]["correct"], "grade": fl["grade"]["correct"], "grade_n": fl["grade"]["n"],
            "salary": fl.get("salary_from", {}).get("correct"), "invalid_quotes": m["invalid_quotes"], "n": len(rows)}


def _tagset(t: dict) -> frozenset:
    return frozenset(t["required"]) | frozenset(t["desired"])


def _resume_quality(per: list[dict], gold: dict) -> dict:
    tp = fp = fn = rtp = rfp = rfn = exp = 0
    for x in per:
        g = gold[x["id"]]
        got, gs = set(x["stack"]), set(g["stack"])
        tp, fp, fn = tp + len(got & gs), fp + len(got - gs), fn + len(gs - got)
        gr, rr = set(g["roles"]), set(x["roles"])
        rtp, rfp, rfn = rtp + len(rr & gr), rfp + len(rr - gr), rfn + len(gr - rr)
        e = x.get("experience_years")
        exp += e is not None and abs(e - g["experience_years"]) <= 0.5
    p, r = round(tp / max(1, tp + fp), 4), round(tp / max(1, tp + fn), 4)
    return {"stack_p": p, "stack_r": r, "stack_f1": f1(p, r), "tp_fp_fn": [tp, fp, fn],
            "roles_p": round(rtp / max(1, rtp + rfp), 3), "roles_r": round(rtp / max(1, rtp + rfn), 3),
            "experience_ok": exp, "n": len(per)}


def _grade_row(d: dict) -> dict:
    s = d["summary"]
    c = s["conditions"]["v2"]
    fmt = s["format"]["v2_1"]
    sec = s["format"].get("v2_2") or {}
    so = s["second_opinion"]
    return {
        "calls": fmt["calls"] + sec.get("calls", 0), "ok": fmt["ok"], "n": fmt["calls"], "format_fail": fmt["format_fail"],
        "transport_fail": fmt["transport_fail"], "p50_s": fmt["latency_s"]["p50"], "p95_s": fmt["latency_s"]["p95"],
        "retried": fmt.get("retried", 0) + sec.get("retried", 0),
        "tokens": {"prompt": fmt["tokens"]["prompt"] + sec.get("tokens", {}).get("prompt", 0),
                   "completion": fmt["tokens"]["completion"] + sec.get("tokens", {}).get("completion", 0)},
        "cost_usd": round((fmt.get("cost_usd") or 0) + (sec.get("cost_usd") or 0), 4) or None,
        "quality": {
            "mae_a": c["vs_gptoss_A"].get("mae"), "r_a": c["vs_gptoss_A"].get("r"),
            "mae_b": c["vs_gptoss_B"].get("mae"), "r_b": c["vs_gptoss_B"].get("r"),
            "bias_b": c["vs_gptoss_B"].get("bias"),
            "ref_strong": c["groups"].get("ref_strong", {}).get("mean"),
            "ref_medium": c["groups"].get("ref_medium", {}).get("mean"),
            "ref_weak": c["groups"].get("ref_weak", {}).get("mean"),
            "order_strict": (c.get("ordering") or {}).get("strict"), "order_n": (c.get("ordering") or {}).get("items"),
            "attacks_pass": c["attacks"]["pass"], "attacks_n": c["attacks"]["n"],
            "expert_honest": c["expert_share_honest"],
            "second_calls": so["second_calls"], "second_share": so["share_of_first_calls"],
            "second_agree": so["agree"], "second_disagree": so["disagree"], "second_failed": so["failed"],
            "second_p50_s": (sec.get("latency_s") or {}).get("p50"),
        },
    }


def build(wdir: Path) -> dict:
    from app.modules.matching import need_parser as NP  # noqa: F401 — тот же код разбора, что у прогона

    vac = json.loads((ROOT / "docs/realdata/vacancies_50.json").read_text())["vacancies"]
    gold = {r["id"]: r["gold"] for r in json.loads((ROOT / "docs/llm/resume_synth.json").read_text())["rows"]}
    rules = {k: _load(wdir / "rules" / f"{k}.json") for k in ("needs", "needs_jury", "resume")}
    sonnet_jury = _load(wdir / slug(SONNET) / "needs_jury.json")
    sonnet_tags = {x["id"]: _tagset(x["tags"]) for x in (sonnet_jury or {}).get("per_text", [])}
    out_funcs = []
    for f in FUNCS:
        rows = {}
        for m in MODELS:
            if m["key"] == "rules":
                rows["rules"] = _rules_row(f["key"], rules, vac, gold, sonnet_tags)
                continue
            d = _load(wdir / slug(m["spec"]) / f"{f['key']}.json")
            if d is None:
                rows[m["key"]] = {"status": "pending"}
                continue
            if f["key"] == "grade":
                row = _grade_row(d)
                row["second_model"] = (d.get("second") or m["spec"]).split("=", 1)[1]
                same = _load(wdir / slug(m["spec"]) / "grade_second_sonnet.json")  # Sonnet → Sonnet: для сравнения
                if same is not None and m["key"] == "sonnet":  # с режимом РФ, где вторая оценка — та же модель
                    so = same["summary"]["second_opinion"]
                    row["quality"]["second_same_model"] = {k: so.get(k) for k in
                                                           ("second_calls", "agree", "disagree", "failed", "mean_abs_delta")}
            else:
                per = d["per_text"]
                row = _calls(per)
                if f["key"] in ("needs_delta", "needs_full"):
                    row["quality"] = _needs_quality(vac, [x["requirements"] for x in per])
                    row["quality"]["dropped_without_quote"] = sum(x.get("dropped_without_quote") or 0 for x in per)
                elif f["key"] == "needs_jury":
                    same = sum(1 for x in per if sonnet_tags.get(x["id"]) == _tagset(x["tags"]))
                    jac = [len(sonnet_tags[x["id"]] & _tagset(x["tags"])) / max(1, len(sonnet_tags[x["id"]] | _tagset(x["tags"])))
                           for x in per if x["id"] in sonnet_tags]
                    row["quality"] = {"same_as_sonnet": same, "n": len(per),
                                      "jaccard_vs_sonnet": round(st.mean(jac), 3) if jac else None}
                elif f["key"] == "resume":
                    row["quality"] = _resume_quality(per, gold)
            row["price"] = _price(m["key"], row, m["spec"])
            row["status"], row["date"] = "done", d.get("date")
            v = _load(wdir / slug(m["spec"]) / "needs_delta_schema.json") if f["key"] == "needs_delta" else None
            if v is not None:  # п.4: та же дельта с JSON-схемой у Yandex (LLM_YANDEX_JSON_SCHEMA=true)
                sv = _calls(v["per_text"])
                sv["quality"] = _needs_quality(vac, [x["requirements"] for x in v["per_text"]])
                sv["schema_rejected"] = sum(1 for x in v["per_text"] if "schema_rejected" in (x.get("attempt_errors") or []))
                row["schema_variant"] = sv
            rows[m["key"]] = row
        out_funcs.append({**f, "rows": rows})
    return out_funcs


def slug(spec: str) -> str:
    import re

    return re.sub(r"[^a-zA-Z0-9.]+", "_", spec).strip("_")


def _rules_row(key: str, rules: dict, vac: list[dict], gold: dict, sonnet_tags: dict) -> dict:
    if key in ("needs_delta", "needs_full") and rules["needs"]:
        return {"status": "done", "quality": _needs_quality(vac, [x["requirements"] for x in rules["needs"]["per_text"]]),
                "p50_s": 0.0, "p95_s": 0.0}
    if key == "needs_jury" and rules["needs_jury"]:
        per = rules["needs_jury"]["per_text"]
        same = sum(1 for x in per if sonnet_tags.get(x["id"]) == _tagset(x["tags"]))
        return {"status": "done", "quality": {"same_as_sonnet": same, "n": len(per)}, "p50_s": 0.0, "p95_s": 0.0}
    if key == "resume" and rules["resume"]:
        return {"status": "done", "quality": _resume_quality(rules["resume"]["per_text"], gold), "p50_s": 0.0,
                "p95_s": 0.0}
    if key == "grade":
        return {"status": "done", "quality": {"expert_honest": 1.0, "attacks_pass": 0},
                "note": "без модели развёрнутый ответ получает статус «на проверке» — оценивает эксперт по рубрике"}
    return {"status": "pending"}


def write_summary(wdir: Path, out: Path) -> dict:
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    d = {
        "title": "Режим «только российская модель»: замер",
        "date": time.strftime("%Y-%m-%d"),
        "code_sha": sha,
        "models": MODELS,
        "functions": build(wdir),
        "inventory": INVENTORY,
        "conditions": CONDITIONS,
        "ref_0810": REF_0810,
        "how_to_enable": HOW,
    }
    y = [f["rows"].get("yandex", {}).get("status") for f in d["functions"]]
    if not all(s == "done" for s in y):
        d["pending_note"] = PENDING_NOTE
    save(d, out)
    return d


def save(d: dict, out: Path = DATA) -> None:
    """Одна копия JSON (по умолчанию — данные /api/validation/ru-llm) и таблица раздела 11 из того же JSON."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_md(d, ROOT / "docs" / "LLM.md")
    print(f"→ {out}")


# ------------------------------------------------------------------ таблица для docs/LLM.md (раздел 11)
MD_BEGIN, MD_END = "<!-- ru_llm:begin (tools/llm/ru_llm_summary.py) -->", "<!-- ru_llm:end -->"


def _n(v, d=3):
    return "—" if v is None else f"{v:.{d}f}".replace(".", ",")


def _cell_md(fkey: str, c: dict, model: str) -> str:
    if not c or c.get("status") != "done":
        return "ещё не замерено"
    q = c.get("quality") or {}
    if fkey in ("needs_delta", "needs_full"):
        out = f"F1 {_n(q['stack_f1'])} (P {_n(q['stack_p'])} / R {_n(q['stack_r'])}); опыт {q['experience']}/{q['n']}"
    elif fkey == "needs_jury":
        out = f"совпало с Sonnet {q['same_as_sonnet']}/{q['n']}"
    elif fkey == "resume":
        out = (f"F1 {_n(q['stack_f1'])} (P {_n(q['stack_p'])} / R {_n(q['stack_r'])}); стаж ±0,5 года "
               f"{q['experience_ok']}/{q['n']}")
    elif fkey == "grade":
        if q.get("mae_b") is None:
            return "все развёрнутые ответы — эксперту"
        out = (f"MAE A / B {_n(q['mae_a'])} / {_n(q['mae_b'])}; атаки {q['attacks_pass']}/{q['attacks_n']}; порядок "
               f"{q['order_strict']}/{q['order_n']}; эксперту {_n(q['expert_honest'] * 100, 1)} % честных; вторая оценка "
               f"{q['second_calls']} ({_n(q['second_share'] * 100, 1)} %), расходится {q['second_disagree']}")
    else:
        out = "—"
    if model == "rules":
        return out
    fails = (c.get("format_fail") or 0) + (c.get("transport_fail") or 0)
    out += f"; ответила {c['ok']}/{c['n']}"
    if fails:
        out += f" (формат {c.get('format_fail') or 0}, сеть {c.get('transport_fail') or 0})"
    out += f"; p50 / p95 {_n(c.get('p50_s'), 2)} / {_n(c.get('p95_s'), 2)} с"
    pr = c.get("price") or {}
    if pr.get("rub_per_1k_calls") is not None:
        out += f"; ≈ {_n(pr['rub_per_1k_calls'], 0)} ₽ / 1000 вызовов"
    sv = c.get("schema_variant")
    if sv:
        out += (f". С JSON-схемой (LLM_YANDEX_JSON_SCHEMA): F1 {_n(sv['quality']['stack_f1'])}, ответила {sv['ok']}/{sv['n']}, "
                f"формат {sv['format_fail']}, схему отклонил {sv['schema_rejected']}, p50 {_n(sv.get('p50_s'), 2)} с")
    return out


def md_table(d: dict) -> str:
    names = [m["label"] for m in d["models"]]
    lines = [MD_BEGIN, "", f"Замер {d['date']}, код `{d['code_sha']}` (данные — `backend/app/modules/validation/data/ru_llm.json`, их же отдаёт `GET /api/validation/ru-llm`).", "",
             "| Функция и набор | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for f in d["functions"]:
        cells = [_cell_md(f["key"], f["rows"].get(m["key"]), m["key"]) for m in d["models"]]
        lines.append(f"| **{f['title']}** — {f['set']} | " + " | ".join(cells) + " |")
    if d.get("pending_note"):
        lines += ["", d["pending_note"]]
    ref = d.get("ref_0810")
    if ref:
        x = ref["needs_full"]
        lines += ["", f"Прежний замер — {ref['label']}: ответила {x['ok']}/{x['n']}, медиана {_n(x['p50_s'], 2)} с, "
                      f"F1 {_n(x['stack_f1'])} (P {_n(x['stack_p'])} / R {_n(x['stack_r'])}); {x['source']}."]
    lines += ["", MD_END]
    return "\n".join(lines)


def write_md(d: dict, path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if MD_BEGIN not in text:
        return
    head, rest = text.split(MD_BEGIN, 1)
    _, tail = rest.split(MD_END, 1)
    path.write_text(head + md_table(d) + tail, encoding="utf-8")


INVENTORY = [
    {"func": "parse_need", "what": "разбор потребности/вакансии: дельта к словарю в фоне (быстрый разбор, раздел 10 docs/LLM.md) и полный запрос (mode=full)",
     "code": "matching/need_parser.py (_call_llm), matching/fast_parse.py", "no_llm": "словарь стек-тегов и правила",
     "bench": "needs_delta, needs_full (50 реальных вакансий), needs_jury (15 текстов)"},
    {"func": "resume", "what": "разбор резюме после вырезания ПДн", "code": "resume/extract.py (extract)",
     "no_llm": "словари и регулярные выражения", "bench": "resume (20 синтетических резюме)"},
    {"func": "grade", "what": "оценка развёрнутого ответа теста, кубка, пакета экспертов", "code": "assessment/grader.py (grade_open)",
     "no_llm": "статус «на проверке» → эксперт", "bench": "grade (набор оценщика, 406 ответов)"},
    {"func": "grade_second", "what": "вторая оценка спорных ответов (у порога, мягкие признаки инъекции, уровень не согласован)",
     "code": "assessment/grader.py, assessment/second_opinion.py", "no_llm": "эксперт",
     "bench": "grade (спорные из того же набора)"},
    {"func": "—", "what": "объяснения подборки, ранжирование, категория, «почему этот кандидат», зонды, подсказки",
     "code": "matching/ranking.py, assignments/why.py и др.", "no_llm": "без LLM всегда (правила)",
     "bench": "не нужен: модели не вызываются"},
]
CONDITIONS = [
    "Одна попытка на вход, без перехода по цепочке и без автомата-выключателя; путь продукта целиком (вырезание ПДн, "
    "проверка цитат, слияние с правилами); параллельно 4 запроса.",
    "Sonnet — с машины замера в OpenRouter напрямую (на стенде — через ретранслятор, там задержка больше); YandexGPT — "
    "Yandex AI Studio, OpenAI-совместимый API.",
    "Задержка p50/p95 — по принятым ответам модели (без правил); «формат» — ответ получен, но продукт его не принял "
    "(не JSON, нет баллов по критериям, не объект); «сеть» — тайм-аут, HTTP ≠ 200.",
    "Цена — на 1000 вызовов: OpenRouter — фактическая (usage.cost), YandexGPT 5.1 — токены × 0,8 ₽ за 1000 "
    "(вход и выход, синхронный режим, с НДС, тариф AI Studio на 09.10.2026); рубли для Sonnet — по курсу ЦБ РФ на 09.10.2026 (85,42 ₽ за $).",
    "Разметки: вакансии — silver-разметка набора (модель + ручная сверка), резюме — автор набора (модель), оценщик — эталон "
    "gpt-oss-120b. Ни одна не экспертная; модели семейства Claude участвовали в разметке атак и резюме — согласие "
    "Sonnet с ними может быть завышено.",
]
REF_0810 = {"label": "YandexGPT 5.1, 08.10 (полный разбор, код c1c248e)", "needs_full": {
    "ok": 50, "n": 50, "p50_s": 2.36, "p90_s": 3.51, "stack_p": 0.853, "stack_r": 0.960, "stack_f1": 0.903,
    "source": "docs/LLM.md, раздел 6"}}
PENDING_NOTE = ("YandexGPT ещё не замерена на этих входах: ключ Yandex AI Studio хранится только на сервере стенда, на "
                "машине замера его нет. Прогон — одной командой, когда ключ будет: tools/llm/ru_llm_bench.py run --model "
                "yandex=yandexgpt-5.1/latest. До этого — замер 08.10 (полный разбор 50 вакансий, код c1c248e).")
HOW = {
    "env": ["LLM_CHAIN=yandex", "LLM_MODEL_PARSE_NEED=yandex=yandexgpt-5.1/latest",
            "LLM_MODEL_RESUME=yandex=yandexgpt-5.1/latest", "LLM_MODEL_GRADE=yandex=yandexgpt-5.1/latest",
            "LLM_MODEL_GRADE_SECOND=yandex=yandexgpt-5.1/latest"],
    "where": ".env сервера (рядом с docker-compose.yml) + ключ Yandex AI Studio в llm.env (LLM_PROVIDER=yandex_ai_studio, "
             "LLM_BASE_URL, LLM_API_KEY, LLM_FOLDER_ID, LLM_MODEL); пересоздать api",
    "check": "/api/meta → llm.chain = [{provider: yandex, configured: true}], functions.*.models[0].label = YandexGPT 5.1",
}
