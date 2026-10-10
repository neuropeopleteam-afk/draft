"""«Рынок по hh.ru» рядом с вилкой приглашения: медиана и p25–p75 вилок живых вакансий роли, грейда и региона.

Честно о том, что считаем (подписи в интерфейсе и docs/INTEGRATIONS.md):
* это **вилки в объявлениях работодателей** на hh.ru (``only_with_salary=true``), а не фактические зарплаты;
* у вакансии с «от» и «до» берём середину, только с «от» — «от», только с «до» — «до»;
* только рубли и оплата за месяц (валюта и почасовые — не считаются, их число показываем);
* hh.ru помечает сумму ``gross`` (до вычета НДФЛ) или нет (на руки): всё приводим к «на руки» по шкале НДФЛ
  13–22 % (``contact.salary``), как рыночный диапазон Хабр Карьеры у категории; доля «до вычета» — в ответе;
* роль — профессиональная роль hh.ru (+ слова в названии), грейд — слово грейда в названии вакансии; если таких
  вакансий в регионе мало — опыт hh.ru как приближение грейда, затем вся Россия. Какая ступень сработала — в ответе;
* меньше ``MIN_SHOW`` вакансий — чисел не показываем («мало данных»), меньше ``MIN_OK`` — показываем с пометкой.

Список вакансий наружу не отдаётся (FTT.6: не витрина чужих вакансий) — только агрегат, n, дата и ссылка на тот
же поиск на hh.ru для самопроверки. Кэш поиска — 24 ч (``hh_market_ttl_s``).
"""
from __future__ import annotations

import statistics
from urllib.parse import urlencode

from app.core.config import get_settings
from app.modules.catalog.seed_data import category_title
from app.modules.contact.salary import gross_of, net_of
from app.modules.hh.client import HhClient, HhError

MIN_SHOW = 8   # меньше — медиану не показываем
MIN_OK = 20    # меньше — «мало данных, ориентир неустойчивый»
PER_PAGE = 100
RUSSIA = ("113", "Россия")
# Направление платформы → профессиональные роли hh.ru и слова в названии (None — роль достаточно узкая сама)
ROLE_QUERY: dict[str, tuple[list[str], list[str] | None]] = {
    "backend": (["96"], ["backend", "бэкенд", "бекенд", "back-end", "python", "java", "golang", "go", "php", "node.js",
                         "c#", ".net", "kotlin", "scala", "ruby", "c++"]),
    "frontend": (["96"], ["frontend", "фронтенд", "front-end", "react", "vue", "angular", "javascript", "typescript"]),
    "qa": (["124"], None),
    "data_ml": (["165", "96"], ["data", "ml", "machine learning", "дата", "машинн", "nlp", "computer vision", "llm"]),
    "security": (["116"], None),
}
GRADE_WORDS = {"intern": ["стажер", "стажёр", "intern", "стажировка", "trainee"],
               "junior": ["junior", "джуниор", "младший"],
               "middle": ["middle", "мидл"],
               "senior": ["senior", "сеньор", "старший", "ведущий", "lead", "тимлид"]}
# Опыт hh.ru как приближение грейда (только если вакансий со словом грейда в названии мало)
GRADE_EXPERIENCE = {"intern": ["noExperience"], "junior": ["noExperience", "between1And3"],
                    "middle": ["between1And3", "between3And6"], "senior": ["between3And6", "moreThan6"]}
EXPERIENCE_TITLES = {"noExperience": "нет опыта", "between1And3": "1–3 года", "between3And6": "3–6 лет",
                     "moreThan6": "более 6 лет"}
AREAS = {"москва": "1", "санкт-петербург": "2", "екатеринбург": "3", "новосибирск": "4", "казань": "88",
         "нижний новгород": "66", "самара": "78", "краснодар": "53", "ростов-на-дону": "76", "пермь": "72",
         "уфа": "99", "воронеж": "26", "челябинск": "104", "омск": "68", "красноярск": "54", "тюмень": "95",
         "томск": "90", "иннополис": "2734", "россия": "113"}


def _q(words: list[str]) -> str:
    return "(" + " OR ".join(f'"{w}"' if " " in w else w for w in words) + ")"


def area_of(city: str | None, cl: HhClient) -> tuple[str, str]:
    """Город → (id региона hh.ru, название); неизвестный — подсказка hh.ru (кэш 30 дней), иначе вся Россия."""
    c = " ".join((city or "").lower().replace("ё", "е").replace("г.", " ").split())
    if not c:
        return RUSSIA
    if c in AREAS:
        return AREAS[c], city.strip()
    try:
        r = cl.get("/suggests/areas", {"text": city.strip()[:60]}, ttl_s=30 * 86400)
        items = r["data"].get("items") or []
        if items:
            return str(items[0]["id"]), str(items[0].get("text") or city)
    except HhError:
        pass
    return RUSSIA


def _value(v: dict) -> tuple[int | None, str]:
    """Вакансия → (сумма на руки за месяц, причина исключения)."""
    sr = v.get("salary_range") or v.get("salary")
    if not sr or not (sr.get("from") or sr.get("to")):
        return None, "no_salary"
    if (sr.get("currency") or "RUR") not in ("RUR", "RUB"):
        return None, "currency"
    mode = (sr.get("mode") or {}).get("id") if isinstance(sr.get("mode"), dict) else None
    if mode not in (None, "MONTH"):
        return None, "mode"
    lo, hi = sr.get("from"), sr.get("to")
    x = (lo + hi) / 2 if lo and hi else (lo or hi)
    x = int(x)
    if sr.get("gross") is True:
        x = net_of(x)
    if not 10_000 <= x <= 3_000_000:
        return None, "outlier"
    return x, "gross" if sr.get("gross") is True else "net"


def _pct(xs: list[int], q: float) -> int:
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return int(round(s[f] + (s[c] - s[f]) * (k - f)))


def _r1000(x: int) -> int:
    return int(round(x / 1000.0)) * 1000


def _params(direction: str, grade: str, area: str, by: str) -> list[tuple[str, str]]:
    roles, words = ROLE_QUERY[direction]
    text = []
    if words:
        text.append(f"NAME:{_q(words)}")
    if by == "name":
        text.append(f"NAME:{_q(GRADE_WORDS[grade])}")
    p = [("professional_role", r) for r in roles] + [("area", area), ("only_with_salary", "true"),
                                                    ("per_page", str(PER_PAGE)), ("order_by", "publication_time")]
    if text:
        p.insert(0, ("text", " AND ".join(text)))
    if by == "experience":
        p += [("experience", e) for e in GRADE_EXPERIENCE[grade]]
    return p


def _search_url(params: list[tuple[str, str]]) -> str:
    keep = [(k, v) for k, v in params if k in ("text", "professional_role", "area", "only_with_salary", "experience")]
    return "https://hh.ru/search/vacancy?" + urlencode(keep)


def _stats(items: list[dict]) -> dict:
    vals, why = [], {"currency": 0, "mode": 0, "outlier": 0, "no_salary": 0}
    gross = 0
    for v in items:
        x, kind = _value(v)
        if x is None:
            why[kind] += 1
            continue
        vals.append(x)
        gross += kind == "gross"
    return {"vals": vals, "excluded": why, "gross": gross}


def market(category_id: str, city: str | None = None, *, remote: bool = False, cl: HhClient | None = None) -> dict:
    """Медиана и p25–p75 (на руки) по живым вакансиям hh.ru; ступени: регион+грейд в названии → регион+опыт →
    Россия+грейд в названии → Россия+опыт (первая с n ≥ MIN_OK, иначе с наибольшим n)."""
    cl = cl or HhClient()
    direction, _, grade = (category_id or "").partition(".")
    if direction not in ROLE_QUERY or grade not in GRADE_WORDS:
        raise HhError(422, "hh_category", "Для этой категории рынок по hh.ru не считается")
    ttl = get_settings().hh_market_ttl_s
    area = RUSSIA if remote else area_of(city, cl)
    steps = [(area, "name"), (area, "experience")]
    if area[0] != RUSSIA[0]:
        steps += [(RUSSIA, "name"), (RUSSIA, "experience")]
    tried, best = [], None
    for (aid, aname), by in steps:
        params = _params(direction, grade, aid, by)
        r = cl.get("/vacancies", params, ttl_s=ttl)
        d = r["data"]
        st = _stats(d.get("items") or [])
        cur = {"area": {"id": aid, "name": aname}, "by": by, "found": int(d.get("found") or 0), "st": st, "meta": r,
               "params": params}
        tried.append({"area": aname, "by": by, "n": len(st["vals"]), "found": cur["found"]})
        if best is None or len(st["vals"]) > len(best["st"]["vals"]):
            best = cur
        if len(st["vals"]) >= MIN_OK:
            best = cur
            break
    st, n = best["st"], len(best["st"]["vals"])
    by_title = (f"слово грейда в названии вакансии ({', '.join(GRADE_WORDS[grade][:3])})" if best["by"] == "name" else
                f"опыт в вакансии hh.ru как приближение грейда: {', '.join(EXPERIENCE_TITLES[e] for e in GRADE_EXPERIENCE[grade])}")
    out = {"available": True, "category_id": category_id, "category_title": category_title(category_id),
           "area": best["area"], "area_requested": {"id": area[0], "name": area[1]},
           "area_fallback": best["area"]["id"] != area[0], "remote": remote, "grade_by": best["by"],
           "grade_by_title": by_title, "n": n, "found": best["found"], "sample": len(best["meta"]["data"].get("items") or []),
           "excluded": st["excluded"], "gross_share": round(st["gross"] / n, 2) if n else None,
           "basis": "net", "as_of": best["meta"]["fetched_at"], "cached": best["meta"]["cached"],
           "stale": best["meta"]["stale"], "stub": best["meta"]["stub"], "tried": tried,
           "search_url": _search_url(best["params"]), "few_data": n < MIN_OK, "shown": n >= MIN_SHOW,
           "median": None, "p25": None, "p75": None, "median_gross": None}
    if n >= MIN_SHOW:
        med = _r1000(int(statistics.median(st["vals"])))
        out.update(median=med, p25=_r1000(_pct(st["vals"], 0.25)), p75=_r1000(_pct(st["vals"], 0.75)),
                   median_gross=_r1000(gross_of(med)))
    out["note"] = note(out)
    return out


def note(m: dict) -> str:
    where = m["area"]["name"] + (f" (в регионе «{m['area_requested']['name']}» вакансий мало)" if m["area_fallback"] else "")
    base = (f"{m['n']} живых вакансий hh.ru с зарплатой в рублях за месяц · {where} · {m['grade_by_title']}. "
            "Это вилки в объявлениях работодателей, не фактические зарплаты; у вилки — середина, у «от» — «от»; "
            f"суммы приведены к «на руки» ({round((m['gross_share'] or 0) * 100)} % вакансий указали сумму до вычета НДФЛ).")
    if not m["shown"]:
        return f"Мало данных: {m['n']} вакансий с зарплатой — медиану не считаем. " + base
    if m["few_data"]:
        return "Мало данных — ориентир неустойчивый. " + base
    return base


def unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason}
