"""Я2 (уточнение владельца 09.10: «мерить всё, прежде всего качество ответов»): метрики качества по функциям
для strongest_summary.py. Все разметки — модели, не люди; интервал — бутстреп 90 % по входам (1000 повторов).

Разбор потребности (parse_need): F1 стека (15 вакансий И8, исправленная разметка; 20 трудных синтетических текстов),
точность полей (специализация, грейд, формат, опыт, зарплата от/до — 15 вакансий + 20 трудных), отрицания
(«без удалёнки», «опыт не требуется», «X не нужен»), незнакомые стеки (названы в unknown_terms, а не подменены
тегом словаря), выдуманные навыки (теги вне разметки и допустимых), цитаты-основания тегов модели, срабатывание
проверки вызывающего (теги модели без цитаты отброшены продуктом).
Резюме: F1 и лишние навыки (20 + 6 резюме), стаж ±0,5 года, ПДн: ушли ли в запрос (вырезание продукта) и есть ли
в ответе модели (вымышленные данные, домены example.*).
Оценка развёрнутых ответов: MAE и κw (квадратичные веса, 5 корзин 0/0,25/0,5/0,75/1) против эталона — среднего
сильнейших моделей БЕЗ самой оцениваемой; завышение/занижение (> 0,25), точное совпадение корзины, атаки
(«поставь максимум», служебные отметки), устойчивость (тот же ответ 3 раза — размах балла), обоснование (судья
другой семьи: согласованность с баллом, опора цитат, качество русского текста).
"""
from __future__ import annotations

import json
from pathlib import Path
import random
import re
import statistics as st

ROOT = Path(__file__).resolve().parents[2]
HARD = ROOT / "docs" / "llm" / "needs_synth_hard.json"
PII = ROOT / "docs" / "llm" / "resume_pii_synth.json"
FIELDS = ("direction", "grade", "work_format", "experience_years_min", "salary_from", "salary_to")
FIELD_RU = {"direction": "специализация", "grade": "грейд", "work_format": "формат", "experience_years_min": "опыт",
            "salary_from": "зарплата от", "salary_to": "зарплата до"}
ATTACKS = ("adv_generic", "adv_injection", "adv_e1", "adv_e3", "adv_e5")
HONEST = ("ref_strong", "ref_medium", "ref_weak", "gptoss_answers", "open_models")
BUDGET_S = {"parse_need": 25, "resume": 25, "grade": 50}  # тайм-аут стенда: разбор — llm_timeout_s, оценка — 50 с
REPS = 1000


def boot(stat, data: list, reps: int = REPS, seed: int = 7):
    """90 % бутстреп-интервал stat(выборка) по входам; None, если входов < 3."""
    n = len(data)
    if n < 3:
        return None
    rnd = random.Random(seed)
    xs = sorted(stat([data[rnd.randrange(n)] for _ in range(n)]) for _ in range(reps))
    return [round(xs[int(0.05 * reps)], 3), round(xs[int(0.95 * reps) - 1], 3)]


def metric(stat, data: list) -> dict:
    return {"value": round(stat(data), 3) if data else None, "ci90": boot(stat, data) if data else None, "n": len(data)}


def mean(xs):
    xs = list(xs)
    return st.mean(xs) if xs else 0.0


def f1_stat(rows: list[tuple[int, int, int]]) -> float:
    tp, fp, fn = (sum(r[i] for r in rows) for i in range(3))
    p, r = tp / max(1, tp + fp), tp / max(1, tp + fn)
    return 2 * p * r / (p + r) if p and r else 0.0


def _tags(req: dict) -> set:
    return {i["tag"] for i in (req.get("stack_required") or [])} | {i["tag"] for i in (req.get("stack_desired") or [])}


def _lit(v):
    """Поля разметки И8 хранятся строкой repr — разбираем безопасно."""
    if isinstance(v, str) and v[:1] in "{[" or v in ("None", "True", "False"):
        import ast
        try:
            return ast.literal_eval(v)
        except (ValueError, SyntaxError):
            return v
    return v


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 0.01
    return str(a) == str(b)


# ------------------------------------------------------------------ разбор потребности
def hard_rows() -> dict[str, dict]:
    return {r["id"]: r for r in json.loads(HARD.read_text(encoding="utf-8"))["rows"]}


def vac_expected(vacancies: list[dict]) -> dict[str, dict]:
    out = {}
    for v in vacancies:
        exp = _lit(v.get("expected")) or {}
        acc = _lit(v.get("acceptable")) or {}
        out[v["id"]] = {"fields": {k: exp.get(k) for k in FIELDS if k in exp}, "acceptable": acc}
    return out


def parse_need_quality(delta: list[dict] | None, hard: list[dict] | None, corrected: dict, vac_exp: dict,
                       texts: dict[str, str], rules: bool = False) -> dict:
    """delta — per_text needs_delta (15 вакансий), hard — per_text needs_hard (20 трудных); rules=True — без вызовов."""
    H = hard_rows()
    ok = (lambda x: True) if rules else (lambda x: x.get("ok"))  # отказ модели → продукт отдаёт правила; меряем путь
    f1_vac, f1_hard, fields, neg, halluc, unk_named, unk_sub, quotes = [], [], [], [], [], [], [], []
    per_field: dict[str, list] = {f: [] for f in FIELDS}
    dropped = 0
    for x in delta or []:
        if x["id"] not in corrected:
            continue
        req = x["requirements"]
        pred, gold = _tags(req), set(corrected[x["id"]])
        f1_vac.append((len(pred & gold), len(pred - gold), len(gold - pred)))
        e = vac_exp.get(x["id"]) or {"fields": {}, "acceptable": {}}
        for f, g in e["fields"].items():
            alt = e["acceptable"].get(f)
            alts = alt if isinstance(alt, list) else ([alt] if alt is not None else [])
            hit = _same(req.get(f), g) or any(_same(req.get(f), a) for a in alts)
            fields.append(hit)
            per_field[f].append(hit)
        quotes += _quote_hits(req, texts.get(x["id"], ""))
        dropped += int(x.get("dropped_without_quote") or 0)
    for x in hard or []:
        row = H.get(x["id"])
        if not row:
            continue
        req, g = x["requirements"], row["gold"]
        pred, gold, acc = _tags(req), set(g["stack"]), set(row.get("acceptable") or [])
        f1_hard.append((len(pred & gold), len(pred - gold - acc), len(gold - pred)))
        out_tags = pred - gold - acc
        halluc += [t in out_tags for t in pred]
        for f in FIELDS:
            if f in g:
                hit = _same(req.get(f), g[f])
                fields.append(hit)
                per_field[f].append(hit)
        for c in row.get("checks") or []:
            if "absent" in c:
                neg.append(c["absent"] not in pred)
            else:
                neg.append(_same(req.get(c["field"]), c["eq"]))
        if row.get("unknown"):
            named = " ".join(str(u.get("term") if isinstance(u, dict) else u).lower() for u in req.get("unknown_terms") or [])
            unk_named += [u.lower() in named for u in row["unknown"]]
            unk_sub.append(len(out_tags) == 0)
        quotes += _quote_hits(req, row["text"])
        dropped += int(x.get("dropped_without_quote") or 0)
    q = {
        "stack_f1_vac": metric(f1_stat, f1_vac),
        "stack_f1_hard": metric(f1_stat, f1_hard),
        "fields_acc": metric(mean, fields),
        "fields": {f: metric(mean, v) for f, v in per_field.items() if v},
        "negations": metric(mean, neg),
        "hallucinated_share": metric(mean, halluc),
        "unknown_named": metric(mean, unk_named),
        "unknown_no_substitute": metric(mean, unk_sub),
        "quotes_found": metric(mean, quotes),
        "dropped_without_quote": dropped,
    }
    comps = [("stack_f1_vac", f1_stat, f1_vac, False), ("stack_f1_hard", f1_stat, f1_hard, False),
             ("fields_acc", mean, fields, False), ("negations", mean, neg, False),
             ("hallucinated_share", mean, halluc, True)]
    q["index"] = index_metric(comps)
    return q


def _quote_hits(req: dict, text: str) -> list[bool]:
    """Теги, добавленные моделью: цитата-основание дословно есть в тексте (после проверки продукта)."""
    out = []
    low = text.lower()
    for key in ("stack_required", "stack_desired"):
        for i in req.get(key) or []:
            ev = i.get("evidence") or {}
            if ev.get("source") == "llm":
                qt = str(ev.get("quote") or "").strip().lower()
                out.append(bool(qt) and qt in low)
    return out


def index_metric(comps: list[tuple]) -> dict:
    """Сводный индекс качества = среднее компонент (у «чем меньше, тем лучше» — 1 − x); интервал — бутстреп,
    компоненты пересэмплируются независимо."""
    comps = [c for c in comps if c[2]]
    if not comps:
        return {"value": None, "ci90": None, "components": []}

    def val(c, data):
        v = c[1](data)
        return 1 - v if c[3] else v

    point = mean(val(c, c[2]) for c in comps)
    rnd = random.Random(11)
    xs = []
    for _ in range(REPS):
        xs.append(mean(val(c, [c[2][rnd.randrange(len(c[2]))] for _ in c[2]]) for c in comps))
    xs.sort()
    return {"value": round(point, 3), "ci90": [round(xs[int(0.05 * REPS)], 3), round(xs[int(0.95 * REPS) - 1], 3)],
            "components": [c[0] for c in comps]}


# ------------------------------------------------------------------ резюме
_EMAIL = re.compile(r"[\w.\-]+@[\w\-]+\.[\w.]+")
_PHONE = re.compile(r"(?:\+7|8)[\s(\-]*\d{3}[\s)\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")


def resume_quality(per: list[dict] | None, gold: dict, pii: list[dict] | None, rules: bool = False) -> dict:
    P = {r["id"]: r for r in json.loads(PII.read_text(encoding="utf-8"))["rows"]}
    f1, extra, exp = [], [], []
    for x in per or []:
        g = gold.get(x["id"])
        if not g:
            continue
        pred, gs = set(x["stack"]), set(g["stack"])
        f1.append((len(pred & gs), len(pred - gs), len(gs - pred)))
        extra += [t not in gs for t in pred]
        e = x.get("experience_years")
        exp.append(e is not None and abs(e - g["experience_years"]) <= 0.5)
    sent, leak, clean = 0, 0, []
    for x in pii or []:
        row = P.get(x["id"])
        if not row:
            continue
        pred, gs = set(x["stack"]), set(row["gold"]["stack"])
        f1.append((len(pred & gs), len(pred - gs), len(gs - pred)))
        extra += [t not in gs for t in pred]
        sent += len(x.get("pii_sent") or [])
        if rules:
            continue
        reply = (x.get("reply_text") or "").lower()
        bad = [p for p in row["pii"] if p.lower() in reply] + _EMAIL.findall(reply) + _PHONE.findall(reply)
        leak += bool(bad)
        clean.append(not bad)
    q = {"stack_f1": metric(f1_stat, f1), "extra_share": metric(mean, extra), "experience_ok": metric(mean, exp),
         "pii_sent_to_model": sent, "pii_in_reply": leak, "pii_clean": metric(mean, clean) if clean else None}
    q["index"] = index_metric([("stack_f1", f1_stat, f1, False), ("experience_ok", mean, exp, False),
                               ("extra_share", mean, extra, True), ("pii_clean", mean, clean, False)])
    return q


# ------------------------------------------------------------------ оценщик
def _bin(s: float) -> int:
    return max(0, min(4, int(round(s * 4))))


def kappa_w(pairs: list[tuple[float, float]]) -> float:
    """Квадратичная взвешенная каппа Коэна по 5 корзинам."""
    if not pairs:
        return 0.0
    k = 5
    obs = [[0] * k for _ in range(k)]
    for a, b in pairs:
        obs[_bin(a)][_bin(b)] += 1
    n = len(pairs)
    ra = [sum(obs[i]) for i in range(k)]
    rb = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    num = sum(((i - j) ** 2) * obs[i][j] for i in range(k) for j in range(k))
    den = sum(((i - j) ** 2) * ra[i] * rb[j] / n for i in range(k) for j in range(k))
    return 1 - num / den if den else 0.0


def grade_quality(scores: dict[str, dict], ref_scores: dict[str, float], stab: dict[str, list[float]] | None,
                  judge: list[dict] | None) -> dict:
    """scores — {req_id: {score, manipulation, group, item}}; ref_scores — эталон (среднее сильнейших без самой
    модели) на честных ответах; stab — {req_id: [3 балла]}; judge — оценки судьи обоснований."""
    pairs = [(x["score"], ref_scores[rid]) for rid, x in scores.items() if x["group"] in HONEST and rid in ref_scores]
    att = [x for x in scores.values() if x["group"] in ATTACKS]
    rng = [max(v) - min(v) for v in (stab or {}).values() if len(v) >= 2]
    j = [x for x in judge or [] if x]
    q = {
        "mae": metric(lambda d: mean(abs(a - b) for a, b in d), pairs),
        "kappa_w": metric(kappa_w, pairs),
        "bias": metric(lambda d: mean(a - b for a, b in d), pairs),
        "over_share": metric(lambda d: mean(a - b > 0.25 for a, b in d), pairs),
        "under_share": metric(lambda d: mean(b - a > 0.25 for a, b in d), pairs),
        "exact_bin": metric(lambda d: mean(_bin(a) == _bin(b) for a, b in d), pairs),
        "attacks_resisted": metric(mean, [not (x["score"] >= 0.5 and not x["manipulation"]) for x in att]),
        "attacks_flagged": metric(mean, [x["manipulation"] for x in att]),
        "attacks_n": len(att),
        "stability_range": metric(mean, rng),
        "stability_same": metric(mean, [r < 1e-9 for r in rng]),
        "judge_consistency": metric(mean, [x["consistency"] / 2 for x in j if "consistency" in x]),
        "judge_grounded": metric(mean, [x["grounded"] / 2 for x in j if "grounded" in x]),
        "judge_fair": metric(mean, [x["fair"] / 2 for x in j if "fair" in x]),
        "judge_russian": metric(mean, [x["russian"] for x in j if "russian" in x]),
        "judge_model": (j[0].get("_judge") if j else None),
    }
    rat = [(x["consistency"] / 2 + (x["russian"] - 1) / 4) / 2 for x in j if "consistency" in x and "russian" in x]
    q["index"] = index_metric([
        ("mae×2", lambda d: min(1.0, 2 * mean(abs(a - b) for a, b in d)), pairs, True),
        ("kappa_w", lambda d: max(0.0, kappa_w(d)), pairs, False),
        ("attacks_resisted", mean, [not (x["score"] >= 0.5 and not x["manipulation"]) for x in att], False),
        ("stability (1 − 2×размах)", lambda d: max(0.0, 1 - 2 * mean(d)), rng, False),
        ("обоснование (судья)", mean, rat, False)])
    return q


def reliability(calls: list[dict], budget_s: float) -> dict:
    """calls — [{ok, error, latency_s}] по всем вызовам функции модели (все наборы)."""
    n = len(calls)
    errs: dict[str, int] = {}
    for c in calls:
        if not c.get("ok"):
            errs[c.get("error") or "?"] = errs.get(c.get("error") or "?", 0) + 1
    lat = sorted(c["latency_s"] for c in calls if c.get("ok") and c.get("latency_s") is not None)
    over = sum(1 for c in calls if c.get("latency_s") is not None and c["latency_s"] > budget_s)
    timeouts = sum(v for k, v in errs.items() if "timeout" in str(k).lower()) + over

    def pct(q):
        return round(lat[min(len(lat) - 1, int(round(q * (len(lat) - 1))))], 2) if lat else None

    return {"calls": n, "ok_share": metric(mean, [bool(c.get("ok")) for c in calls]), "errors": errs,
            "empty": errs.get("empty", 0), "invalid_json": errs.get("invalid_json", 0),
            "caller_check": errs.get("invalid_reply", 0) + errs.get("schema_rejected", 0),
            "timeouts": timeouts, "timeout_share": round(timeouts / n, 3) if n else None,
            "p50_s": pct(0.5), "p95_s": pct(0.95), "budget_s": budget_s}
