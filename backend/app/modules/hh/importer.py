"""Своя вакансия работодателя с hh.ru → черновик вакансии платформы (FTT.5: синхронизация из внешней системы найма).

Работодатель вставляет ссылку или номер СВОЕЙ вакансии; платформа читает её одним запросом ``GET /vacancies/{id}`` и
создаёт черновик с источником «hh.ru», ссылкой и датой импорта. Поиска и витрины чужих вакансий нет (FTT.6):
если работодатель в hh.ru не совпадает по названию с компанией на платформе, импорт требует явного подтверждения
«это вакансия нашей компании», а черновик виден только своей компании до публикации.

Маппинг (``map_vacancy``) — тот же разбор, что у потребности и импорта из «Потока» (``need_parser.parse_need``,
правила, без LLM): название + описание (HTML → текст) + key_skills → направление, грейд, стек, формат; key_skills
добавляются к стеку как навыки, указанные работодателем. Опыт, график и занятость — строкой «Условия с hh.ru» в
описании (отдельных полей у вакансии нет), опыт — ещё и подсказка грейда, если грейда нет в тексте. Вилка — из
``salary_range`` (``salary``), если обе границы в рублях за месяц и ширина ≤ 1,5; основание — ``gross`` hh.ru
(до вычета НДФЛ / на руки). Только «от» (или «до») или шире 1,5 — вторая граница достраивается (× 1,25 / обрезка
до 1,5 × «от») с пометкой «уточните»; нет суммы или не рубли за месяц — рыночный диапазон категории (на руки).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import utcnow
from app.integrations.vacancies.ats_import import EXPERIENCE_HINT, EXPERIENCE_TITLES, _market, edited_after_import, html_to_text
from app.integrations.vacancies.models import Vacancy
from app.modules.catalog.dictionary import find_stack
from app.modules.catalog.models import Category
from app.modules.catalog.seed_data import STACK, known_tag
from app.modules.hh.client import HhClient, HhError

SOURCE = "hh"
SOURCE_TITLE = "hh.ru"
MAX_RATIO = 1.5
PARTIAL_RATIO = 1.25  # только «от» (или «до») в hh.ru: вторая граница черновика — × (÷) 1,25, с пометкой «уточните»
FORMAT_MAP = {"REMOTE": "remote", "ON_SITE": "office", "HYBRID": "hybrid"}
FORMAT_TITLES = {"remote": "удалённо", "office": "офис", "hybrid": "гибрид", "any": "любой"}
_ID_RE = re.compile(r"^\s*(\d{5,12})\s*$")
_URL_RE = re.compile(r"^\s*(?:https?://)?(?:[\w-]+\.)*(?:hh\.ru|headhunter\.ru|hh\.kz|hh\.uz|rabota\.by)/"
                     r"(?:vacancy|vacancies)/(\d{5,12})(?:[/?#].*)?\s*$", re.I)
_LEGAL = re.compile(r"\b(ооо|оао|зао|пао|ао|ип|нко|ано|llc|ltd|inc|gmbh|группа компаний|гк)\b", re.I)


def parse_ref(ref: str) -> str:
    """Номер вакансии из ссылки hh.ru (hh.ru/vacancy/123, spb.hh.ru/vacancy/123?from=…) или из самого номера."""
    s = (ref or "").strip()
    m = _ID_RE.match(s) or _URL_RE.match(s)
    if not m:
        raise HhError(422, "hh_bad_ref", "Вставьте ссылку на вакансию hh.ru (например, https://hh.ru/vacancy/123456789) "
                                         "или её номер")
    return m.group(1)


def public_url(vid: str) -> str:
    return f"https://hh.ru/vacancy/{vid}"


def _norm(name: str | None) -> str:
    s = (name or "").lower().replace("ё", "е")
    s = re.sub(r"^демо[^:]*:", "", s)
    s = _LEGAL.sub(" ", s)
    s = re.sub(r"[^\w]+", " ", s)
    return " ".join(s.split())


def same_company(hh_name: str | None, our_name: str | None) -> bool | None:
    """Совпадает ли работодатель hh.ru с компанией на платформе (без юрформы, кавычек, регистра). None — неизвестно."""
    a, b = _norm(hh_name), _norm(our_name)
    if not a or not b:
        return None
    return a == b or (len(a) >= 4 and a in b) or (len(b) >= 4 and b in a)


def salary_of(v: dict) -> dict | None:
    """salary_range (новое поле hh.ru) или salary: {from, to, currency, gross, mode}."""
    sr = v.get("salary_range") or v.get("salary")
    if not sr:
        return None
    mode = (sr.get("mode") or {}).get("id") if isinstance(sr.get("mode"), dict) else None
    return {"from": sr.get("from"), "to": sr.get("to"), "currency": sr.get("currency") or "RUR",
            "gross": sr.get("gross"), "mode": mode or "MONTH"}


def _rub(v: int) -> str:
    return f"{v:,}".replace(",", "\u00a0") + "\u00a0₽"


def salary_text(sal: dict | None) -> str:
    if not sal or not (sal.get("from") or sal.get("to")):
        return "не указана"
    cur = "₽" if sal["currency"] in ("RUR", "RUB") else sal["currency"]
    f = lambda x: f"{x:,}".replace(",", "\u00a0")  # noqa: E731
    parts = ([f"от {f(sal['from'])}"] if sal.get("from") else []) + ([f"до {f(sal['to'])}"] if sal.get("to") else [])
    basis = "" if sal.get("gross") is None else (" до вычета НДФЛ" if sal["gross"] else " на руки")
    mode = "" if sal.get("mode") in (None, "MONTH") else f" ({ {'HOUR': 'за час', 'DAY': 'за день', 'SHIFT': 'за смену', 'FLY_IN_FLY_OUT': 'за вахту'}.get(sal['mode'], sal['mode'])})"
    return f"{' '.join(parts)} {cur}{basis}{mode}"


def work_format_of(v: dict) -> str | None:
    ids = [x.get("id") for x in v.get("work_format") or [] if isinstance(x, dict)]
    mapped = list(dict.fromkeys(FORMAT_MAP[i] for i in ids if i in FORMAT_MAP))
    if len(mapped) == 1:
        return mapped[0]
    if len(mapped) > 1:
        return "hybrid" if "hybrid" in mapped else "any"
    sched = (v.get("schedule") or {}).get("id")  # прежнее поле hh.ru (до work_format)
    return "remote" if sched == "remote" else None


def conditions_line(v: dict) -> str:
    """«Условия с hh.ru: опыт 3–6 лет · график 5/2, 8 часов · формат гибрид · занятость полная»."""
    parts = []
    if (v.get("experience") or {}).get("name"):
        parts.append(f"опыт: {v['experience']['name'].lower()}")
    sched = [x.get("name") for x in (v.get("work_schedule_by_days") or []) + (v.get("working_hours") or []) if x.get("name")]
    if not sched and (v.get("schedule") or {}).get("name"):
        sched = [v["schedule"]["name"]]
    if sched:
        parts.append(f"график: {', '.join(sched)}")
    wf = [x.get("name") for x in v.get("work_format") or [] if x.get("name")]
    if wf:
        parts.append(f"формат: {', '.join(n.lower() for n in wf)}")
    emp = (v.get("employment_form") or v.get("employment") or {}).get("name")
    if emp:
        parts.append(f"занятость: {emp.lower()}")
    return ("Условия с hh.ru — " + " · ".join(parts) + ".") if parts else ""


@dataclass
class Mapped:
    external_id: str
    title: str
    description: str
    category_id: str | None
    stack: list[str]
    stack_from_key_skills: list[str]
    salary_from: int
    salary_to: int
    salary_basis: str
    salary_from_hh: bool
    work_format: str
    city: str | None
    archived: bool
    employer_name: str | None
    experience: str | None
    key_skills: list[str]
    salary_hh: str
    conditions: str
    salary_source: str = "market"  # hh — вилка из hh.ru, hh_partial — достроена по одной границе, market — рынок
    notes: list[str] = field(default_factory=list)
    parsed: dict = field(default_factory=dict)

    def fields(self) -> dict:
        return {"title": self.title, "description": self.description, "category_id": self.category_id,
                "stack": self.stack, "salary_from": self.salary_from, "salary_to": self.salary_to,
                "salary_basis": self.salary_basis, "work_format": self.work_format, "city": self.city}


def map_vacancy(db: Session, v: dict) -> Mapped:
    from app.modules.matching.need_parser import parse_need

    vid = str(v.get("id"))
    title = (v.get("name") or "").strip()[:200] or f"Вакансия hh.ru № {vid}"
    if len(title) < 3:
        title = f"{title} (№ {vid})"
    text = html_to_text(v.get("description"))
    skills = [s.get("name", "") if isinstance(s, dict) else str(s) for s in v.get("key_skills") or []]
    skills = [s.strip() for s in skills if s and s.strip()]
    notes: list[str] = []
    parsed = parse_need(" ".join(x for x in (title, text, ", ".join(skills)) if x), use_llm=False)
    direction, grade = parsed.get("direction"), parsed.get("grade")
    exp = (v.get("experience") or {}).get("id")
    if not grade and exp in EXPERIENCE_HINT:
        grade = EXPERIENCE_HINT[exp]
        notes.append(f"Грейд в тексте не указан — подставлен по опыту из hh.ru ({EXPERIENCE_TITLES[exp]}) как подсказка; "
                     "грейд кандидата подтверждает тест навыков, уточните категорию")
    category_id = f"{direction}.{grade}" if direction and grade else None
    if category_id and db.get(Category, category_id) is None:
        category_id = None
    if not category_id:
        notes.append("Категорию по тексту определить не удалось — выберите её перед публикацией")
    from_text = [s["tag"] for s in (parsed.get("stack_required") or []) + (parsed.get("stack_desired") or [])
                 if known_tag(s.get("tag"))]
    from_ks = [t for s in skills for t in sorted(find_stack(s), key=find_stack(s).get) if known_tag(t)]
    stack = list(dict.fromkeys(from_text + from_ks))[:20]
    sal = salary_of(v)
    lo, hi = (sal or {}).get("from"), (sal or {}).get("to")
    rub = bool(sal) and sal["currency"] in ("RUR", "RUB") and sal["mode"] == "MONTH"
    from_hh = bool(rub and lo and hi and 0 < int(lo) <= int(hi) <= int(lo) * MAX_RATIO)
    source = "hh" if from_hh else "market"
    if from_hh:
        lo, hi, basis = int(lo), int(hi), ("net" if sal.get("gross") is False else "gross")
    elif rub and (lo or hi) and (not (lo and hi) or 0 < int(lo) <= int(hi)):
        # частично из hh.ru: только «от» / только «до» / шире 1,5 — достраиваем вторую границу, основание то же
        basis, source = ("net" if sal.get("gross") is False else "gross"), "hh_partial"
        if lo and not hi:
            lo, hi = int(lo), int(int(lo) * PARTIAL_RATIO) // 1000 * 1000
            how = f"«до» подставлено как «от» × {PARTIAL_RATIO:.2f}".replace(".", ",")
        elif hi and not lo:
            hi = int(hi)
            lo = -(-int(hi / PARTIAL_RATIO) // 1000) * 1000
            how = f"«от» подставлено как «до» ÷ {PARTIAL_RATIO:.2f}".replace(".", ",")
        else:
            lo = int(lo)
            hi = int(lo * MAX_RATIO) // 1000 * 1000
            how = f"«до» уменьшено до {hi:,} ₽".replace(",", "\u00a0")
        why = "указана только «от»" if not sal.get("to") else "указана только «до»" if not sal.get("from") else "шире 1,5 раза"
        notes.append(f"Вилка в hh.ru {why} ({salary_text(sal)}) — {how}; уточните «от–до» перед публикацией "
                     "(вилка обязательна, «до» не больше 1,5 × «от»)")
    else:
        m = _market(db, category_id) or (100_000, 150_000)
        why = ("не указана" if not sal or not (lo or hi) else "указана не в рублях за месяц" if not rub
               else "указана только «от»" if lo and not hi else "указана только «до»" if hi and not lo
               else "шире 1,5 раза")
        notes.append(f"Вилка в hh.ru {why} ({salary_text(sal)}) — подставлен рыночный диапазон категории (на руки); "
                     "уточните «от–до» перед публикацией (вилка обязательна, «до» не больше 1,5 × «от»)")
        (lo, hi), basis = m, "net"
    cond = conditions_line(v)
    body = text if len(text) >= 20 else (text + "\n" if text else "") + f"Импортировано с hh.ru, вакансия № {vid}."
    if cond:
        body = f"{body}\n\n{cond}"
    hh_fmt = work_format_of(v)
    work_format = hh_fmt or parsed.get("work_format") or "any"
    if work_format not in ("office", "hybrid", "remote", "any"):
        work_format = "any"
    city = ((v.get("area") or {}).get("name") or "").strip()[:100] or parsed.get("city")
    archived = bool(v.get("archived"))
    if archived:
        notes.append("В hh.ru вакансия в архиве — проверьте, актуальна ли она, перед публикацией")
    return Mapped(external_id=vid, title=title, description=body[:5000], category_id=category_id, stack=stack,
                  stack_from_key_skills=[t for t in dict.fromkeys(from_ks) if t not in from_text],
                  salary_from=lo, salary_to=hi, salary_basis=basis, salary_from_hh=from_hh, salary_source=source,
                  work_format=work_format,
                  city=city, archived=archived, employer_name=(v.get("employer") or {}).get("name"),
                  experience=(v.get("experience") or {}).get("name"), key_skills=skills, salary_hh=salary_text(sal),
                  conditions=cond, notes=notes, parsed=parsed)


def fetch(vid: str, cl: HhClient | None = None) -> tuple[dict, dict]:
    cl = cl or HhClient()
    r = cl.get(f"/vacancies/{vid}", ttl_s=get_settings().hh_vacancy_ttl_s, allow_stale=False)
    return r["data"], r


def _existing(db: Session, company_id, vid: str) -> Vacancy | None:
    return db.scalar(select(Vacancy).where(Vacancy.company_id == company_id, Vacancy.source == SOURCE,
                                           Vacancy.external_id == vid))


def _state(v: Vacancy | None, m: Mapped) -> str:
    if v is None:
        return "new"
    if edited_after_import(v):
        return "edited"
    return "same" if all(getattr(v, k) == val for k, val in m.fields().items()) else "changed"


STATE_TITLES = {"new": "новая — будет создан черновик", "same": "уже импортирована, без изменений",
                "changed": "уже импортирована, в hh.ru изменилась — поля обновятся",
                "edited": "уже импортирована и изменена на платформе — не перезаписываем"}


def _summary(m: Mapped, company, raw: dict, meta: dict, existing: Vacancy | None) -> dict:
    st = _state(existing, m)
    own = same_company(m.employer_name, getattr(company, "name", None))
    notes = list(m.notes)
    if own is not True:
        notes.insert(0, f"Работодатель вакансии в hh.ru — «{m.employer_name or 'не указан'}», а ваша компания на "
                        f"платформе — «{company.name}». Импортируйте только вакансии своей компании: подтвердите, что "
                        "это ваша вакансия")
    return {"hh_id": m.external_id, "url": public_url(m.external_id), "title": m.title, "employer_name": m.employer_name,
            "own_company": own, "confirm_required": own is not True, "archived": m.archived,
            "experience": m.experience, "conditions": m.conditions, "salary_hh": m.salary_hh,
            "key_skills": m.key_skills, "category_id": m.category_id, "stack": m.stack,
            "stack_from_key_skills": m.stack_from_key_skills,
            "stack_titles": [STACK.get(t, (t,))[0] for t in m.stack], "salary_from": m.salary_from,
            "salary_to": m.salary_to, "salary_basis": m.salary_basis, "salary_from_hh": m.salary_from_hh,
            "salary_source": m.salary_source,
            "work_format": m.work_format, "city": m.city, "description_preview": m.description[:600],
            "parse_method": m.parsed.get("method") or "rules", "notes": notes, "state": st, "state_title": STATE_TITLES[st],
            "vacancy_id": str(existing.id) if existing else None, "fetched_at": meta.get("fetched_at"),
            "stub": bool(meta.get("stub"))}


def preview(db: Session, company, ref: str, cl: HhClient | None = None) -> dict:
    vid = parse_ref(ref)
    raw, meta = fetch(vid, cl)
    m = map_vacancy(db, raw)
    return _summary(m, company, raw, meta, _existing(db, company.id, vid))


def run_import(db: Session, company, user, ref: str, *, confirm_own: bool = False, cl: HhClient | None = None) -> dict:
    """Создать (или обновить) черновик по вакансии hh.ru. В hh.ru — только чтение GET /vacancies/{id}."""
    vid = parse_ref(ref)
    raw, meta = fetch(vid, cl)
    m = map_vacancy(db, raw)
    v = _existing(db, company.id, vid)
    out = _summary(m, company, raw, meta, v)
    if out["confirm_required"] and not confirm_own:
        raise HhError(409, "hh_confirm_own", "Подтвердите, что это вакансия вашей компании: импортировать можно только "
                                             "свои вакансии (чужие вакансии платформа не собирает)")
    st = out["state"]
    if st in ("same", "edited"):
        return {**out, "result": "skipped", "text": STATE_TITLES[st]}
    now = utcnow()
    if v is None:
        v = Vacancy(company_id=company.id, created_by=user.id, is_demo=user.is_demo, source=SOURCE, external_id=vid,
                    external_url=public_url(vid), status="draft", published_at=None, **m.fields())
        db.add(v)
        result, text = "created", "Создан черновик — проверьте поля и опубликуйте"
    else:
        for k, val in m.fields().items():
            setattr(v, k, val)
        v.external_url = public_url(vid)
        result, text = "updated", "Черновик обновлён по hh.ru"
    v.imported_at = v.updated_at = now  # правка работодателем позже — updated_at > imported_at
    db.commit()
    return {**out, "result": result, "text": text, "vacancy_id": str(v.id), "state": st,
            "imported_at": now.isoformat()}


__all__ = ["HhError", "map_vacancy", "parse_ref", "preview", "run_import", "same_company", "SOURCE", "SOURCE_TITLE"]
