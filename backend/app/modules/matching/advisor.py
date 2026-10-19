"""Н1: «ИИ-советник руководителя» на экране сравнения кандидатов (POST /api/employer/needs/{id}/advisor).

Руководитель задаёт вопрос голосом или текстом («Кого позвать первым и почему?», «У кого лучше соотношение навыков и
зарплатной вилки?»…) — советник отвечает по тем же фактам, что и таблица сравнения (matching.compare): балл
соответствия, θ ± SE, достоверность результата теста, навыки потребности (подтверждены тестом / проверены ниже
порога / только заявлены / нет данных), достижения из реестра ФСП, задания с вилкой, рынок категории и вилка
потребности. Ответ собирается правилами из этих фактов — без генерации текста моделью: каждая цифра в ответе есть
в таблице под панелью, ничего не выдумывается и не уходит во внешние сервисы (ПДн нет и в самом сравнении).

Ответ — несколько абзацев для экрана (``answer``), короткий текст для озвучивания (``speech``: без «₽», «%», «θ»
и кодов, которые синтез речи читает плохо) и разбор по кандидатам (``candidates``) для карточек панели.
Скрытый минимум зарплаты кандидата не используется никогда: ориентир по деньгам — рынок категории кандидата и
вилка потребности (как в строке «Ожидания по рынку категории»).
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.core.fmt import ru_num
from app.modules.catalog.seed_data import tag_title
from app.modules.contact.salary import to_net
from app.modules.matching import compare as compare_mod
from app.modules.matching.models import EmployerNeed
from app.modules.profiles.models import Company

SOURCE_NOTE = ("Ответ собран правилами по данным сравнения: балл, тест, навыки, реестр ФСП, рынок. Текст не генерируется "
               "моделью — каждая цифра есть в таблице ниже")

INTENTS: dict[str, str] = {
    "briefing": "Краткий доклад",
    "first": "Кого позвать первым",
    "salary": "Навыки и зарплатная вилка",
    "questions": "Вопросы на финальный созвон",
    "fsp": "Достижения ФСП",
    "risks": "Риски и непроверенное",
    "skill": "Сравнение по навыку",
    "candidate": "Разбор кандидата",
}

CHIPS = ["Кого позвать первым и почему?", "У кого лучше соотношение навыков и зарплатной вилки?",
         "О чём спросить лидера на финальном созвоне?", "Чем отличаются их достижения ФСП?"]

_RULES: list[tuple[str, re.Pattern]] = [
    ("salary", re.compile(r"зарплат|вилк|деньг|оклад|бюджет|стоим|дорог|дешев|соотношени|рынок|рыноч", re.I)),
    ("questions", re.compile(r"спрос|вопрос|созвон|собеседован|интервью|уточн|о ч[её]м|проверить на", re.I)),
    ("fsp", re.compile(r"фсп|достижен|соревнован|олимпиад|турнир|чемпионат|спортивн|кубок", re.I)),
    ("risks", re.compile(r"риск|слаб|непровер|не провер|сомнен|опасен|подвох|красн|минус|недостат", re.I)),
    ("first", re.compile(r"перв|лидер|лучш|сильн|кого (?:позвать|пригласить|брать|выбрать)|выбрать|победит|топ", re.I)),
]
_REF = re.compile(r"\bC-[A-Z0-9]{4,}\b", re.I)


def _rub_k(v: int | float | None) -> str:
    """240 000 → «240 тыс. ₽» (неразрывные пробелы)."""
    if not v:
        return "—"
    return f"{round(v / 1000):,}".replace(",", "\u00a0") + "\u00a0тыс.\u00a0₽"


def _range(lo, hi) -> str:
    """200 000 и 280 000 → «200–280 тыс. ₽»."""
    if lo and hi:
        return f"{round(lo / 1000):,}–{round(hi / 1000):,}".replace(",", "\u00a0") + "\u00a0тыс.\u00a0₽"
    return f"от {_rub_k(lo)}" if lo else f"до {_rub_k(hi)}" if hi else "не указана"


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{round(v * 100)}\u00a0%"


def _pts(x: float) -> str:
    return ru_num(abs(x), 1)


def classify(question: str | None, refs: list[str], tags: dict[str, str]) -> tuple[str, str | None]:
    """Намерение вопроса и его объект (ref кандидата или тег навыка). Пусто — краткий доклад."""
    q = (question or "").strip()
    if not q:
        return "briefing", None
    for m in _REF.finditer(q):
        ref = next((r for r in refs if r.upper() == m.group(0).upper()), None)
        if ref:
            return "candidate", ref
    low = q.lower()
    for name, rx in _RULES:
        if rx.search(low):
            return name, None
    for tag, title in tags.items():  # «А что с Kafka?» — сравнение по одному навыку потребности
        if re.search(rf"(?<![\w]){re.escape(title.lower())}(?![\w])", low) or re.search(
                rf"(?<![\w]){re.escape(tag.lower())}(?![\w])", low):
            return "skill", tag
    return "briefing", None


# ------------------------------------------------------------------ факты кандидата из сравнения

def _facts(c: dict, rows: list[dict], req: dict) -> dict:
    cells = c["cells"]
    zone = {r["key"]: r["group"] for r in rows}
    confirmed, weak, declared, missing = [], [], [], []
    for key, cell in cells.items():
        if not key.startswith("stack:"):
            continue
        tag = key.split(":", 1)[1]
        item = {"tag": tag, "title": tag_title(tag), "required": zone.get(key) == "Обязательно",
                "value": cell.get("value")}
        st = cell.get("status")
        if st == "confirmed" or cell.get("implied_via"):
            confirmed.append(item)
        elif st == "mismatch":
            weak.append(item)
        elif st == "declared":
            declared.append(item)
        else:
            missing.append(item)
    req_total = len(req.get("stack_required") or [])
    req_conf = sum(1 for x in confirmed if x["required"])
    integ = (cells.get("integrity") or {}).get("integrity")
    fsp_cell = cells.get("fsp") or {}
    fsp = fsp_cell.get("text") if fsp_cell.get("level") == "T2" else None
    probe = cells.get("probe") or {}
    cat = c.get("category") or {}
    grade_cell = cells.get("category") or {}
    theta = cells.get("theta") or {}
    risks: list[str] = []
    if grade_cell.get("status") == "missing":
        risks.append("нет результата теста — уровень не подтверждён")
    elif grade_cell.get("provisional"):
        risks.append("грейд пока предварительный")
    elif "ниже запрошенного" in (grade_cell.get("text") or ""):
        risks.append("грейд на ступень ниже запрошенного")
    if integ == "medium":
        risks.append("достоверность теста средняя — стоит устная защита или короткое задание")
    elif integ == "low":
        risks.append("достоверность теста низкая — результат нужно перепроверить")
    miss_req = [x["title"] for x in weak + declared + missing if x["required"]]
    if miss_req:
        risks.append("обязательное без подтверждения тестом: " + ", ".join(miss_req))
    core = cells.get("core") or {}
    if core.get("state") == "absent":
        risks.append("ядро роли не заявлено — смежное направление")
    mk = cells.get("market") or {}
    if mk.get("status") == "mismatch":
        risks.append("верх вашей вилки ниже рынка его категории — возможен отказ")
    market = c.get("market_range") or {}
    return {
        "ref": c["ref"], "score": c["score"], "score100": round(c["score"] * 100), "rank": c.get("rank_in_selection"),
        "category_title": cat.get("title"), "provisional": bool(grade_cell.get("provisional")),
        "has_test": grade_cell.get("status") not in ("missing", "unconfirmed"),
        "theta": theta.get("theta"), "se": theta.get("se"),
        "integrity": integ, "integrity_text": (cells.get("integrity") or {}).get("text"),
        "confirmed": confirmed, "weak": weak, "declared": declared, "missing": missing,
        "required_total": req_total, "required_confirmed": req_conf,
        "fsp": fsp, "fsp_strength": float(fsp_cell.get("value") or 0.0) if fsp else 0.0,
        "probe": probe.get("text") if probe.get("level") == "T1" else None,
        "market": {"from": market.get("from"), "to": market.get("to"), "median": market.get("median")} if market else None,
        "market_status": mk.get("status"),
        "defense": (cells.get("defense") or {}).get("text") if (cells.get("defense") or {}).get("level") == "T1" else None,
        "risks": risks,
    }


def _skills_line(f: dict, limit: int = 3) -> str:
    xs = sorted(f["confirmed"], key=lambda x: (not x["required"], -(x["value"] or 0)))[:limit]
    if not xs:
        return "тестом из стека потребности ничего не подтверждено"
    return "подтверждено тестом: " + ", ".join(f"{x['title']} {_pct(x['value'])}" if x["value"] is not None
                                              else x["title"] for x in xs)


def _req_share(f: dict) -> str:
    return (f"{f['required_confirmed']} из {f['required_total']} обязательных навыков подтверждены тестом"
            if f["required_total"] else "обязательных навыков в потребности нет")


def _integrity_word(v: str | None) -> str:
    return {"high": "высокая", "medium": "средняя", "low": "низкая"}.get(v or "", "нет сведений")


def _leader(fs: list[dict]) -> dict:
    return max(fs, key=lambda f: (f["score"], f["required_confirmed"], f["fsp_strength"]))


def _why_for(why: list[dict], a: str, b: str) -> dict | None:
    return next((w for w in why if w["higher"] == a and w["lower"] == b), None)


def _need_salary(req: dict) -> tuple[str, int | None]:
    lo, hi = req.get("salary_from"), req.get("salary_to")
    basis = "на руки" if req.get("salary_net") else "до вычета НДФЛ"
    if not (lo or hi):
        return "в потребности вилка не указана", None
    top_net = to_net(hi or lo, "net" if req.get("salary_net") else "gross")
    return f"{_range(lo, hi)} {basis}", top_net


# ------------------------------------------------------------------ ответы по намерениям

_THETA = re.compile(r"θ\s*([+−-]?\d+(?:[.,]\d+)?)\s*±\s*(\d+(?:[.,]\d+)?)")


def _factor(p: dict) -> str:
    """Фактор «почему выше» из сравнения простыми словами (как plainText на экране, без θ и SE):
    «тест: θ +1,27 ± 0,49 против θ +1,00 ± 0,44» → «уровень по тесту выше, но в пределах точности теста»."""
    if p.get("label") == "тест":
        a, b = _THETA.search(str(p.get("a") or "")), _THETA.search(str(p.get("b") or ""))
        if a and b:
            f = lambda x: float(x.replace("−", "-").replace(",", "."))  # noqa: E731
            sure = f(a[1]) - f(a[2]) > f(b[1]) + f(b[2])
            return "уровень по тесту выше, с запасом" if sure else "уровень по тесту выше, но в пределах точности теста"
        return "уровень по тесту выше"
    return str(p.get("text") or "")


def _first(fs: list[dict], why: list[dict]) -> list[str]:
    order = sorted(fs, key=lambda f: -f["score"])
    a = order[0]
    out = [f"Первым позовите {a['ref']}: {a['score100']} из 100 по подтверждённым фактам, {_req_share(a)}; "
           f"{_skills_line(a)}."]
    extra = []
    if a["fsp"]:
        extra.append(f"в реестре ФСП: {a['fsp']}")
    if a["integrity"]:
        extra.append(f"достоверность теста {_integrity_word(a['integrity'])}")
    if a["probe"]:
        extra.append(f"задание с вилкой: {a['probe']}")
    if extra:
        out.append("Плюс " + "; ".join(extra) + ".")
    for b in order[1:]:
        w = _why_for(why, a["ref"], b["ref"]) if b is order[1] else None
        if w and w["diff"] < 0.5:
            out.append(f"{b['ref']} почти вровень ({b['score100']} из 100): разницу решит короткое задание с вилкой.")
        elif w and w.get("pro"):
            reasons = "; ".join(_factor(p) for p in w["pro"][:2])
            out.append(f"{b['ref']} — {b['score100']} из 100, ниже на {_pts(w['diff'])} балла: {reasons}.")
        else:
            out.append(f"{b['ref']} — {b['score100']} из 100, {_req_share(b)}.")
    if a["risks"]:
        out.append(f"Что проверить у лидера до оффера: {a['risks'][0]}.")
    return out


def _salary(fs: list[dict], req: dict) -> list[str]:
    need_txt, top_net = _need_salary(req)
    out = [f"Ваша вилка — {need_txt}. Ожидания кандидатов скрыты и в подбор не входят, поэтому ориентир — рынок "
           f"категории кандидата на руки."]
    by_market: dict[tuple, list[dict]] = {}
    for f in fs:
        m = f["market"] or {}
        by_market.setdefault((f["category_title"], m.get("from"), m.get("to"), m.get("median")), []).append(f)
    for (title, lo, hi, med), group in by_market.items():
        who = "у всех" if len(group) == len(fs) and len(fs) > 1 else "у " + ", ".join(g["ref"] for g in group)
        line = f"Рынок {title or 'категории'} ({who}) — {_range(lo, hi)}" + (f", медиана {_rub_k(med)}" if med else "")
        if top_net and lo and top_net < lo:
            line += "; верх вашей вилки ниже рынка — возможен отказ"
        elif top_net and med and top_net < med:
            line += "; верх вашей вилки ниже медианы рынка"
        elif top_net and hi and top_net > hi:
            line += "; верх вашей вилки выше рынка — сильный аргумент в приглашении"
        elif top_net:
            line += "; вилка в пределах рынка"
        out.append(line + ".")
    scored = []
    for f in fs:
        m = f["market"] or {}
        med = m.get("median") or (((m.get("from") or 0) + (m.get("to") or 0)) / 2 or None)
        share = (f["required_confirmed"] / f["required_total"]) if f["required_total"] else f["score"]
        scored.append((f, med, share, (share / (med / 100_000)) if med else None))
    best = [x for x in scored if x[3] is not None]
    if best:
        f, med, share, _ = max(best, key=lambda x: (x[3], x[0]["score"]))
        same = len(by_market) == 1
        if same and len({round(x[2], 3) for x in best}) == 1:
            out.append(f"Рынок и доля подтверждённого обязательного стека ({_pct(share)}) у всех одинаковы — по деньгам "
                       f"они равны, решает балл: выше всех {f['ref']}, {f['score100']} из 100.")
        elif same:
            out.append(f"Рынок одной категории, поэтому соотношение решают подтверждённые навыки: больше всех у "
                       f"{f['ref']} — {_req_share(f)} ({_pct(share)}) за ту же вилку.")
        else:
            out.append(f"Лучшее соотношение у {f['ref']}: {_pct(share)} обязательного стека подтверждено при медиане "
                       f"рынка {_rub_k(med)} — больше проверенных навыков на каждый рубль вилки.")
    out.append("Точную сумму подтвердит приглашение: вилка в нём обязательна, кандидат видит её до ответа.")
    return out


def _questions(fs: list[dict], need_title: str) -> list[str]:
    a = _leader(fs)
    qs: list[str] = []
    for x in (a["declared"] + a["weak"] + a["missing"]):
        if x["required"]:
            how = ("тест проверил ниже порога" if x in a["weak"] else "заявлено, тестом не проверено"
                   if x in a["declared"] else "данных нет")
            qs.append(f"{x['title']} ({how}): попросите разобрать реальную задачу — что делал сам, какие были "
                      f"компромиссы и как проверял результат.")
        if len(qs) >= 2:
            break
    if a["integrity"] in ("medium", "low"):
        qs.append("Попросите устно пройти ход решения одного из развёрнутых ответов теста — это снимет вопрос о "
                  "самостоятельности.")
    if a["fsp"]:
        qs.append(f"Про ФСП ({a['fsp'].split(';')[0]}): какую часть задачи решал лично, как команда делила работу и "
                  f"что сделал бы иначе сейчас.")
    top = sorted(a["confirmed"], key=lambda x: -(x["value"] or 0))[:1]
    if top:
        qs.append(f"Сильная сторона — {top[0]['title']}: дайте задачу на уровень выше потребности «{need_title}», "
                  f"чтобы понять потолок.")
    qs.append("Ожидания по деньгам и сроку выхода — сверить с вашей вилкой до финального решения.")
    out = [f"На финальном созвоне с {a['ref']} я бы спросила:"]
    out += [f"{i}. {q}" for i, q in enumerate(qs[:5], start=1)]
    return out


def _fsp(fs: list[dict]) -> list[str]:
    with_fsp = sorted([f for f in fs if f["fsp"]], key=lambda f: -f["fsp_strength"])
    without = [f["ref"] for f in fs if not f["fsp"]]
    if not with_fsp:
        return ["Подтверждённых реестром ФСП достижений нет ни у кого из сравниваемых — это без штрафа: решают тест "
                "и навыки. Отличить кандидатов поможет короткое задание с вилкой или Кубок работодателя."]
    out = []
    for f in with_fsp:
        out.append(f"{f['ref']}: {f['fsp']}.")
    if len(with_fsp) >= 2:
        a, b = with_fsp[0], with_fsp[1]
        out.append(f"Сильнее паспорт ФСП у {a['ref']}: сила {ru_num(a['fsp_strength'])} против "
                   f"{ru_num(b['fsp_strength'])} у {b['ref']}.")
    if without:
        out.append(f"У {', '.join(without)} подтверждённых достижений нет — без штрафа, бонус ФСП просто не начислен.")
    out.append("В балл входят только достижения, подтверждённые реестром ФСП; заявленные кандидатом без подтверждения "
               "не учитываются.")
    return out


def _risks(fs: list[dict]) -> list[str]:
    out: list[str] = []
    for f in sorted(fs, key=lambda f: -f["score"]):
        unv = [x["title"] for x in f["declared"]]
        parts = list(f["risks"])
        if unv:
            parts.append("заявлено без проверки тестом: " + ", ".join(unv[:4]))
        out.append(f"{f['ref']}: " + ("; ".join(parts) if parts else "явных рисков по данным нет") + ".")
    out.append("Любой непроверенный навык закрывается коротким заданием с вилкой прямо из сравнения — кнопка "
               "«Задание» в колонке кандидата.")
    return out


def _skill(fs: list[dict], tag: str) -> list[str]:
    title = tag_title(tag)
    out = [f"{title} по сравниваемым:"]
    for f in sorted(fs, key=lambda f: -f["score"]):
        if (x := next((x for x in f["confirmed"] if x["tag"] == tag), None)):
            st = f"подтверждено тестом{(' — ' + _pct(x['value'])) if x['value'] is not None else ''}"
        elif any(x["tag"] == tag for x in f["weak"]):
            st = "проверено тестом, ниже порога подтверждения"
        elif any(x["tag"] == tag for x in f["declared"]):
            st = "только заявлено кандидатом — в балл не входит"
        else:
            st = "нет данных"
        out.append(f"{f['ref']}: {st}.")
    return out


def _candidate(fs: list[dict], ref: str) -> list[str]:
    f = next(x for x in fs if x["ref"] == ref)
    place = sorted(fs, key=lambda x: -x["score"]).index(f) + 1
    out = [f"{ref}: {f['score100']} из 100, {place}-й из {len(fs)} в этом сравнении; {f['category_title'] or 'без категории'}"
           f"{' (предварительно)' if f['provisional'] else ''}."]
    share = _req_share(f)
    out.append(f"{share[:1].upper()}{share[1:]}; {_skills_line(f, 4)}.")
    if f["fsp"]:
        out.append(f"ФСП: {f['fsp']}.")
    out.append(f"Достоверность теста — {_integrity_word(f['integrity'])}.")
    if f["risks"]:
        out.append("Риски: " + "; ".join(f["risks"]) + ".")
    return out


def _briefing(fs: list[dict], why: list[dict], req: dict) -> list[str]:
    order = sorted(fs, key=lambda f: -f["score"])
    a = order[0]
    out = [f"Коротко по {len(fs)} кандидатам. Лидер — {a['ref']}: {a['score100']} из 100, {_req_share(a)}"
           + (f", в реестре ФСП: {a['fsp'].split(';')[0]}" if a["fsp"] else "") + "."]
    if len(order) > 1:
        b = order[1]
        w = _why_for(why, a["ref"], b["ref"])
        gap = f" — разница {_pts(w['diff'])} балла" if w else ""
        out.append(f"Второй — {b['ref']}: {b['score100']} из 100{gap}" + (f"; ФСП: {b['fsp'].split(';')[0]}" if b["fsp"] else "") + ".")
    need_txt, _ = _need_salary(req)
    markets = {f["category_title"]: f["market"] for f in fs if f["market"] and f["category_title"]}
    if markets:
        mt = "; ".join(f"{k} — {_range(v.get('from'), v.get('to'))}" for k, v in list(markets.items())[:2])
        out.append(f"Деньги: ваша вилка {need_txt}; рынок на руки: {mt}.")
    groups: dict[str, list[str]] = {}
    for f in order:
        bits = f["risks"][:2] + (["заявлено без проверки тестом: " + ", ".join(x["title"] for x in f["declared"][:3])]
                                 if f["declared"] else [])
        for b in bits:
            groups.setdefault(b, []).append(f["ref"])
    for risk, who in list(groups.items())[:3]:
        lead_in = "У всех" if len(who) == len(fs) and len(fs) > 1 else "У " + " и ".join(who)
        out.append(f"{lead_in}: {risk} — закрывается коротким заданием с вилкой.")
    out.append("Спросите меня голосом или текстом — например, кого позвать первым или о чём спросить лидера.")
    return out


# ------------------------------------------------------------------ речь

_SPEECH_SUBS = [
    (re.compile(r"\u00a0"), " "),
    (re.compile(r"(\d+)\s*–\s*(\d+)\s*тыс\.\s*₽"), r"от \1 до \2 тысяч рублей"),
    (re.compile(r"(\d+)\s*тыс\.\s*₽"), r"\1 тысяч рублей"),
    (re.compile(r"₽"), "рублей"),
    (re.compile(r"(\d+)\s*%"), r"\1 процентов"),
    (re.compile(r"θ"), "тэта"),
    (re.compile(r"±"), "плюс-минус"),
    (re.compile(r"\bФСП\b"), "Ф-С-П"),
    (re.compile(r"\bНДФЛ\b"), "налога"),
    (re.compile(r"\bC-([A-Z0-9]+)\b"), lambda m: " ".join(m.group(1))),  # код читается по буквам
]


def spoken(lines: list[str], limit: int = 4) -> str:
    """Текст для синтеза речи: первые абзацы, без символов, которые синтез читает плохо."""
    txt = " ".join(lines[:limit])
    for rx, rep in _SPEECH_SUBS:
        txt = rx.sub(rep, txt)
    return re.sub(r"\s+", " ", txt).strip()[:1200]


# ------------------------------------------------------------------ точка входа

def advise(db: Session, company: Company, need: EmployerNeed, refs: list[str], version: int | None,
           question: str | None) -> dict:
    data = compare_mod.compare(db, company, need, refs, version)
    req = data["need"]["requirements"] or {}
    fs = [_facts(c, data["rows"], req) for c in data["candidates"]]
    tags = {it["tag"]: tag_title(it["tag"]) for z in ("stack_required", "stack_desired") for it in req.get(z) or []}
    intent, obj = classify(question, [f["ref"] for f in fs], tags)
    why = data.get("why") or []
    if intent == "first":
        lines = _first(fs, why)
    elif intent == "salary":
        lines = _salary(fs, req)
    elif intent == "questions":
        lines = _questions(fs, data["need"]["title"])
    elif intent == "fsp":
        lines = _fsp(fs)
    elif intent == "risks":
        lines = _risks(fs)
    elif intent == "skill" and obj:
        lines = _skill(fs, obj)
    elif intent == "candidate" and obj:
        lines = _candidate(fs, obj)
    else:
        intent, lines = "briefing", _briefing(fs, why, req)
    if question and intent == "briefing":
        lines = ["Отвечу по данным сравнения — точнее всего я разбираю: кого позвать первым, деньги и навыки, вопросы "
                 "на созвон, ФСП, риски, отдельный навык или кандидата по номеру."] + lines[:-1]
    lead = _leader(fs)
    return {
        "question": (question or "").strip() or None, "intent": intent, "intent_title": INTENTS[intent],
        "answer": lines, "speech": spoken(lines, 5 if intent == "questions" else 4), "leader": lead["ref"],
        "need": {"id": data["need"]["id"], "title": data["need"]["title"], "version": data["need"]["version"]},
        "candidates": [{
            "ref": f["ref"], "score": f["score100"], "rank_in_selection": f["rank"], "category_title": f["category_title"],
            "provisional": f["provisional"], "integrity": f["integrity"],
            "required_confirmed": f["required_confirmed"], "required_total": f["required_total"],
            "confirmed": [x["title"] for x in f["confirmed"]], "unverified": [x["title"] for x in f["declared"]],
            "weak": [x["title"] for x in f["weak"]], "fsp": f["fsp"], "market": f["market"], "risks": f["risks"],
            "leader": f["ref"] == lead["ref"],
        } for f in sorted(fs, key=lambda x: -x["score"])],
        "chips": CHIPS, "source": "rules", "source_note": SOURCE_NOTE,
    }
