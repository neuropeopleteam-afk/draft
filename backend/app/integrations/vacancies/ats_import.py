"""Импорт вакансий из «Потока» в вакансии платформы (И23, ответ организаторов о связке с ATS).

Замыкает цикл «вакансии — отклики — статусы»: вакансия заводится в «Потоке» → кнопкой «Импортировать из ATS» она
появляется на платформе с бейджем «из «Потока»» → кандидаты откликаются → отклик передаётся в ту же вакансию «Потока»
(``AtsConnection.vacancy_map``) → этапы рекрутёра возвращаются обратным каналом (docs/ATS.md §11).

В «Потоке» — только чтение ``GET /jobs.json?by_scope=all`` (``PotokClient.jobs``); ничего не создаём и не меняем.
Персональные данные рекрутёров из ответа (``author``, ``jobs_users``, ``executive_recruiter``) не читаем и не храним.

Маппинг полей (``map_job``):

* ``name`` → название; ``description`` (HTML) → текст без тегов, не короче 20 символов;
* направление, грейд и стек — разбор текста правилами ``need_parser.parse_need(use_llm=False)`` (без LLM);
  ``experience_type`` — только подсказка грейда, если грейда нет в тексте (грейд — уровень навыков, VS.1);
* ``salary_from/salary_to`` в рублях, вилка не шире 1,5 → вилка и публикация; иначе — рыночный диапазон категории,
  статус «Черновик» и заметка «уточните вилку» (ТЗ: вилка обязательна, её задаёт работодатель);
* ``schedule_type: remote`` → удалённо; ``city`` — id региона (как в hh: 1 Москва, 2 Санкт-Петербург …);
* ``archived`` или ``state_id`` не ``opened`` → «Снята».

Дедупликация — уникальный индекс ``(company_id, source, external_id)``: повторный импорт обновляет вакансию, если
работодатель не правил её на платформе после импорта (``updated_at == imported_at``), иначе пропускает с пометкой.
"""
from __future__ import annotations

from dataclasses import dataclass
import html
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import as_aware, utcnow
from app.integrations.ats import providers
from app.integrations.ats.clients import AtsError
from app.integrations.vacancies.models import Vacancy
from app.modules.catalog.models import Category
from app.modules.catalog.seed_data import STACK

SOURCE = "potok"
SOURCE_TITLE = "Поток"
MAX_RATIO = 1.5  # ширина вилки, как у приглашений и вакансий (invitations.service.check_salary)
# id регионов «Потока» (справочник hh.ru) — те, что встречаются у работодателей стенда и в демо-заглушке
AREAS = {"1": "Москва", "2": "Санкт-Петербург", "3": "Екатеринбург", "4": "Новосибирск", "88": "Казань",
         "66": "Нижний Новгород"}
# experience_type «Потока» (как в hh.ru) → грейд-подсказка, только если грейда нет в названии и описании
EXPERIENCE_HINT = {"noExperience": "junior", "between1And3": "junior", "between3And6": "middle", "moreThan6": "senior"}
EXPERIENCE_TITLES = {"noExperience": "без опыта", "between1And3": "1–3 года", "between3And6": "3–6 лет",
                     "moreThan6": "более 6 лет"}
_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</(p|div|li|h[1-6])>|<br\s*/?>", re.I)


def job_url(base: str, job_id) -> str | None:
    """Ссылка на вакансию в интерфейсе «Потока» (только для настоящего API; у демо-заглушки — блок «Этапы из «Потока»»)."""
    return f"https://app.potok.io/j/{job_id}/" if "app.potok.io" in base else None


def html_to_text(raw: str | None) -> str:
    s = _BLOCK.sub("\n", raw or "")
    s = html.unescape(_TAG.sub("", s))
    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in s.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


@dataclass
class Mapped:
    external_id: str
    title: str
    description: str
    category_id: str | None
    stack: list[str]
    salary_from: int
    salary_to: int
    salary_from_ats: bool
    work_format: str
    city: str | None
    closed: bool
    notes: list[str]

    def fields(self) -> dict:
        return {"title": self.title, "description": self.description, "category_id": self.category_id,
                "stack": self.stack, "salary_from": self.salary_from, "salary_to": self.salary_to,
                "work_format": self.work_format, "city": self.city}


def _market(db: Session, category_id: str | None) -> tuple[int, int] | None:
    cat = db.get(Category, category_id) if category_id else None
    if cat is None or not cat.market_salary_from:
        return None
    lo = int(cat.market_salary_from)
    hi = min(int(cat.market_salary_to or lo), int(lo * MAX_RATIO // 1000 * 1000)) or lo
    return lo, max(lo, hi)


def map_job(db: Session, job: dict) -> Mapped:
    from app.modules.matching.need_parser import parse_need

    jid = str(job.get("id"))
    title = (job.get("name") or "").strip()[:200] or f"Вакансия № {jid}"
    if len(title) < 3:
        title = f"{title} (№ {jid})"
    text = html_to_text(job.get("description"))
    skills = [s if isinstance(s, str) else (s or {}).get("name", "") for s in job.get("key_skills") or []]
    notes: list[str] = []
    parsed = parse_need(" ".join(x for x in (title, text, ", ".join(skills)) if x), use_llm=False)
    direction, grade = parsed.get("direction"), parsed.get("grade")
    exp = job.get("experience_type")
    if not grade and exp in EXPERIENCE_HINT:
        grade = EXPERIENCE_HINT[exp]
        notes.append(f"Грейд в тексте не указан — подставлен по опыту из «Потока» ({EXPERIENCE_TITLES[exp]}) как "
                     f"подсказка; грейд кандидата подтверждает тест навыков, уточните категорию")
    category_id = f"{direction}.{grade}" if direction and grade else None
    if category_id and db.get(Category, category_id) is None:
        category_id = None
    if not category_id:
        notes.append("Категорию по тексту определить не удалось — выберите её перед публикацией")
    stack = [s["tag"] for s in (parsed.get("stack_required") or []) + (parsed.get("stack_desired") or [])
             if s.get("tag") in STACK]
    stack = list(dict.fromkeys(stack))[:20]
    lo, hi = job.get("salary_from"), job.get("salary_to")
    from_ats = bool(lo and hi and 0 < int(lo) <= int(hi) and int(hi) <= int(lo) * MAX_RATIO
                    and (job.get("currency_type") or "RUR") in ("RUR", "RUB"))
    if from_ats:
        lo, hi = int(lo), int(hi)
    else:
        m = _market(db, category_id) or (100_000, 150_000)
        why = ("не указана" if not (lo or hi) else "указана не в рублях" if (job.get("currency_type") or "RUR")
               not in ("RUR", "RUB") else "шире 1,5 раза или неполная")
        notes.append(f"Вилка в «Потоке» {why} — подставлен рыночный диапазон категории; уточните её перед "
                     f"публикацией (вилка «от–до» обязательна)")
        lo, hi = m
    if len(text) < 20:
        text = (text + "\n" if text else "") + f"Импортировано из «Потока», вакансия № {jid}."
    text = text[:5000]
    sched = job.get("schedule_type")
    work_format = "remote" if sched == "remote" else (parsed.get("work_format") or "any")
    if work_format not in ("office", "hybrid", "remote", "any"):
        work_format = "any"
    city_raw = str(job.get("city") or "").strip()
    city = AREAS.get(city_raw) if city_raw.isdigit() else (city_raw[:100] or None)
    closed = bool(job.get("archived")) or (job.get("state_id") or "opened") != "opened"
    return Mapped(external_id=jid, title=title, description=text, category_id=category_id, stack=stack,
                  salary_from=lo, salary_to=hi, salary_from_ats=from_ats, work_format=work_format, city=city,
                  closed=closed, notes=notes)


def _client(db: Session, company_id):
    """Клиент «Потока» компании; AtsError 422 «не задан токен» — понятное сообщение без токена."""
    pr = providers.make(db, company_id, SOURCE)
    return pr.cl


def _existing(db: Session, company_id) -> dict[str, Vacancy]:
    rows = db.scalars(select(Vacancy).where(Vacancy.company_id == company_id, Vacancy.source == SOURCE)).all()
    return {v.external_id: v for v in rows}


def _linked(db: Session, company_id) -> dict[str, Vacancy]:
    """Вакансии платформы, вручную связанные с вакансией «Потока» в «Интеграции с ATS» (vacancy_map), — не дублируем."""
    conn = providers.connection(db, company_id, SOURCE, create=False)
    ids = {k: str((m or {}).get("id")) for k, m in ((conn.vacancy_map or {}) if conn else {}).items() if (m or {}).get("id")}
    if not ids:
        return {}
    rows = db.scalars(select(Vacancy).where(Vacancy.company_id == company_id)).all()
    return {ids[str(v.id)]: v for v in rows if str(v.id) in ids and v.source != SOURCE}


def _same_title(db: Session, company_id) -> dict[str, Vacancy]:
    """Свои (не импортированные) вакансии по названию — подсказка «возможно, дубль»."""
    rows = db.scalars(select(Vacancy).where(Vacancy.company_id == company_id, Vacancy.source.is_(None))).all()
    return {" ".join(v.title.lower().split()): v for v in rows}


def _similar_note(v: Vacancy) -> str:
    return (f"На платформе уже есть вакансия «{v.title}» — проверьте, не дубль ли; по умолчанию не выбрана. "
            "Чтобы отклики на неё уходили в «Поток», свяжите её в «Интеграции с ATS»")


def edited_after_import(v: Vacancy) -> bool:
    ua, ia = as_aware(v.updated_at), as_aware(v.imported_at)
    return bool(ia and ua and ua > ia)  # при импорте updated_at := imported_at, любая правка позже сдвигает updated_at


def _state(v: Vacancy | None, m: Mapped) -> str:
    if v is None:
        return "new"
    if edited_after_import(v):
        return "edited"
    same = all(getattr(v, k) == val for k, val in m.fields().items()) and (v.status == "closed") == m.closed
    return "same" if same else "changed"


STATE_TITLES = {"new": "новая", "same": "уже импортирована, без изменений", "changed": "изменилась в «Потоке»",
                "edited": "уже импортирована и изменена на платформе — не перезаписываем",
                "linked": "уже связана с вакансией платформы — не дублируем"}


def preview(db: Session, company_id) -> dict:
    cl = _client(db, company_id)
    jobs = cl.jobs(scope="all")
    have, linked, titled = _existing(db, company_id), _linked(db, company_id), _same_title(db, company_id)
    items = []
    for j in jobs:
        m = map_job(db, j)
        v = have.get(m.external_id)
        similar = None
        if v is None and m.external_id in linked:
            st, v = "linked", linked[m.external_id]
        else:
            st = _state(v, m)
            similar = titled.get(" ".join(m.title.lower().split())) if st == "new" else None
        notes = m.notes + ([_similar_note(similar)] if similar else [])
        items.append({"job_id": j.get("id"), "title": m.title, "closed": m.closed, "state": st,
                      "state_title": STATE_TITLES[st], "vacancy_id": str(v.id) if v else None,
                      "similar_vacancy_id": str(similar.id) if similar else None,
                      "category_id": m.category_id, "stack": m.stack, "salary_from": m.salary_from,
                      "salary_to": m.salary_to, "salary_from_ats": m.salary_from_ats, "city": m.city,
                      "work_format": m.work_format, "notes": notes,
                      "applicants": (j.get("applicants_count") or {}).get("all"),
                      "url": job_url(cl.base, j.get("id"))})
    return {"provider": SOURCE, "provider_title": SOURCE_TITLE, "demo": "app.potok.io" not in cl.base,
            "total": len(items), "items": items}


def run_import(db: Session, company, user, job_ids: list[int] | None, *, publish: bool = True) -> dict:
    """Импорт выбранных (или всех) вакансий. В «Потоке» — только GET /jobs.json."""
    cl = _client(db, company.id)
    jobs = cl.jobs(scope="all")
    want = {str(x) for x in job_ids} if job_ids else None
    have, linked = _existing(db, company.id), _linked(db, company.id)
    conn = providers.connection(db, company.id, SOURCE, create=False)
    vmap = dict(conn.vacancy_map or {}) if conn else {}
    out = {"created": 0, "updated": 0, "skipped": 0, "items": []}
    for j in jobs:
        jid = str(j.get("id"))
        if want is not None and jid not in want:
            continue
        m = map_job(db, j)
        v = have.get(jid)
        if v is None and jid in linked:  # связана вручную: отклики уже уходят в эту вакансию «Потока» — не дублируем
            lv = linked[jid]
            out["skipped"] += 1
            out["items"].append({"job_id": j.get("id"), "vacancy_id": str(lv.id), "title": lv.title, "result": "skipped",
                                 "state": "linked", "text": STATE_TITLES["linked"], "notes": []})
            continue
        st = _state(v, m)
        now = utcnow()
        if st == "edited" and m.closed and v.status != "closed":
            # закрытие в «Потоке» доходит и до вакансии, которую работодатель правил: остальные поля не трогаем
            v.status = "closed"
            db.flush()
            out["updated"] += 1
            out["items"].append({"job_id": j.get("id"), "vacancy_id": str(v.id), "title": v.title, "result": "updated",
                                 "state": st, "status": v.status, "notes": [],
                                 "text": "Снята — закрыта в «Потоке» (остальные поля изменены на платформе, не трогаем)"})
            continue
        if st in ("same", "edited"):
            out["skipped"] += 1
            out["items"].append({"job_id": j.get("id"), "vacancy_id": str(v.id), "title": v.title, "result": "skipped",
                                 "state": st, "text": STATE_TITLES[st], "notes": []})
            continue
        if v is None:
            ready = publish and m.salary_from_ats and m.category_id and not m.closed
            v = Vacancy(company_id=company.id, created_by=user.id, salary_basis="gross", is_demo=user.is_demo,
                        source=SOURCE, external_id=jid, external_url=job_url(cl.base, jid), **m.fields(),
                        status="closed" if m.closed else "published" if ready else "draft",
                        published_at=now if ready else None)
            db.add(v)
            result = "created"
        else:
            for k, val in m.fields().items():
                setattr(v, k, val)
            if m.closed:
                v.status = "closed"
            v.external_url = job_url(cl.base, jid)
            result = "updated"
        v.imported_at = v.updated_at = now  # правка работодателем позже — updated_at > imported_at
        db.flush()
        # отклики на эту вакансию передаются в ту же вакансию «Потока» (ats.service._target), этапы — обратным каналом
        vmap[str(v.id)] = {**(vmap.get(str(v.id)) or {}), "id": int(jid), "title": m.title}
        out[result] += 1
        out["items"].append({"job_id": j.get("id"), "vacancy_id": str(v.id), "title": v.title, "result": result,
                             "state": st, "status": v.status, "notes": m.notes,
                             "text": ("Создана" if result == "created" else "Обновлена")
                             + (" и опубликована" if v.status == "published" and result == "created" else
                                " — черновик, уточните перед публикацией" if v.status == "draft" else
                                " — снята (закрыта в «Потоке»)" if v.status == "closed" else "")})
    if conn is not None:
        conn.vacancy_map = vmap
    db.commit()
    return out


__all__ = ["AtsError", "map_job", "preview", "run_import", "html_to_text", "SOURCE", "SOURCE_TITLE"]
