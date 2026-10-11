"""«Поток Рекрутмент» (potok.io): открытое REST API v3, документация https://api-doc.potok.io/
(спецификация OpenAPI 3.1 — https://api-doc.potok.io/potok-api-v3.yml).

Базовый адрес ``https://app.potok.io/api/v3``. Токен компании создаётся в Потоке: настройки компании →
«Генерация токенов» (доступ — по ролевой модели). Передаётся ``Authorization: Bearer <token>`` (или ``?token=``).
Есть ограничение частоты запросов (429). Ошибки: 401 токен, 402 подписка просрочена, 422 валидация
(``{"errors": {"поле": ["…"]}}``).

Передача кандидата:
1. ``POST /applicants.json`` — кандидат: ФИО, emails, phones (с кодом страны), accounts (Telegram),
   ``source_type: sourced``, ``source_url`` — адрес платформы (источник из справочника «Источники кандидатов»),
   ``resumes[0].cv_params``: title (категория), skills (HTML профиля), about_me (оффер), skill_set (подтверждённые
   навыки T1), education.attestation (адаптивный тест T1), awards (достижения ФСП T2), certificate (PDF-профиль);
   ``events [{body, type}]`` — комментарий (именно список: объект «Поток» отклоняет с 500); ``ajs_joins [{job_id}]`` — сразу на выбранную вакансию;
2. повтор с известным id: ``POST /ajs_joins.json`` (job_id, applicant_id, stage_type: sourced) — на другую вакансию;
   ответ 422 «кандидат на вакансии уже существует» — уже добавлен, это не ошибка;
3. ``POST /ajs_joins/{id}/change_stage.json`` — на выбранный этап (необязательно);
4. ``POST /events.json`` (type Event::Comment, job_id) — комментарий при повторной передаче.
Поиска кандидата по почте в API нет, поэтому дубликаты исключаем своей связью «кандидат платформы → id в Потоке».
"""
from __future__ import annotations

import json

import httpx

from app.integrations.ats import clients as http
from app.integrations.ats import profile as prof
from app.integrations.ats.clients import AtsError, check_url
from app.integrations.ats.providers.base import LinkState, Provider, Target, soft
from app.integrations.ats.providers.talantix import user_agent
from app.integrations.settings import get_isettings

BASE_URL = "https://app.potok.io/api/v3"
DOCS_URL = "https://api-doc.potok.io/"
CARD_URL = "https://app.potok.io/j/{job}/{stage}/a/{applicant}/"


class PotokClient:
    def __init__(self, base_url: str, token: str, timeout: float | None = None):
        self.base = check_url(base_url.rstrip("/"))
        self.token = token
        self.timeout = timeout or get_isettings().ats_timeout_s

    def _req(self, method: str, path: str, body: dict | None = None, params: dict | None = None):
        try:
            r = http._send(method, self.base + path, json=body, params=params, timeout=self.timeout,
                           headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json",
                                    "User-Agent": user_agent()})
        except httpx.HTTPError as e:
            raise AtsError(f"«Поток» недоступен ({type(e).__name__})") from None
        if r.status_code == 401:
            raise AtsError("«Поток»: токен недействителен (401)", 401)
        if r.status_code == 402:
            raise AtsError("«Поток»: подписка компании просрочена (402)", 402)
        if r.status_code == 429:
            raise AtsError("«Поток»: превышен лимит частоты запросов (429)", 429)
        if r.status_code >= 400:
            try:
                d = r.json()
                detail = json.dumps(d.get("errors", d) if isinstance(d, dict) else d, ensure_ascii=False)[:240]
            except ValueError:
                detail = r.text[:200]
            raise AtsError(f"«Поток» ответил {r.status_code}: {detail}", r.status_code)
        try:
            return r.json()
        except ValueError:
            return {}

    def jobs(self, scope: str = "active", per_page: int = 100) -> list[dict]:
        out, page = [], 1
        while page <= 10:
            d = self._req("GET", "/jobs.json", params={"by_scope": scope, "page": page, "per_page": per_page})
            items = d.get("data") or d.get("objects") or [] if isinstance(d, dict) else d
            out += items
            if len(items) < per_page:
                break
            page += 1
        return out

    def job(self, job_id: int) -> dict:
        d = self._req("GET", f"/jobs/{job_id}.json")
        data = d.get("data", d) if isinstance(d, dict) else d
        if isinstance(data, list):  # в спецификации ответ описан так же, как список: {"data": [...]}
            data = next((j for j in data if j.get("id") == job_id), data[0] if data else {})
        return data or {}

    def create_applicant(self, applicant: dict) -> dict:
        return self._req("POST", "/applicants.json", {"applicant": applicant})

    def join(self, job_id: int, applicant_id: int, stage_type: str = "sourced") -> dict | None:
        """Кандидат на вакансию. None — уже на этой вакансии (422 «кандидат на вакансии уже существует»)."""
        try:
            return self._req("POST", "/ajs_joins.json", {"job_id": job_id, "applicant_id": applicant_id,
                                                         "stage_type": stage_type})
        except AtsError as e:
            if e.status == 422 and "уже существует" in str(e):
                return None
            raise

    def change_stage(self, join_id: int, stage_id: int) -> dict:
        return self._req("POST", f"/ajs_joins/{join_id}/change_stage.json", {"stage_id": stage_id})

    def join_state(self, job_id: int, applicant_id: int) -> dict | None:
        """Этап кандидата на вакансии (обратный канал): ``GET /jobs/{job_id}/ajs_joins.json?applicant_id=…`` →
        ``{id, stage: {id, stage_type}, active}``; ``active: false`` — кандидат отклонён на вакансии.
        Если метод недоступен компании (403/404), — ``GET /applicants/{id}.json`` (этап есть, признака отказа нет).
        None — кандидата на вакансии нет."""
        try:
            d = self._req("GET", f"/jobs/{job_id}/ajs_joins.json", params={"applicant_id": applicant_id})
            objs = d.get("objects") or [] if isinstance(d, dict) else []
            j = next((o for o in objs if o.get("applicant_id") in (applicant_id, None)), None)
            if j is None:
                return None
            # в спецификации — и «stage: {id, stage_type}» (схема), и «stage_id» (пример ответа): принимаем оба
            stg = j.get("stage") or {}
            return {"id": j.get("id"), "stage_id": stg.get("id") or j.get("stage_id"),
                    "stage_type": stg.get("stage_type"), "active": j.get("active", True), "source": "ajs_joins"}
        except AtsError as e:
            if e.status not in (403, 404):
                raise
        a = self._req("GET", f"/applicants/{applicant_id}.json")
        j = next((x for x in (a.get("ajs_joins") or []) if (x.get("job") or {}).get("id") == job_id), None)
        if j is None:
            return None
        st = j.get("stage") or {}
        return {"id": j.get("id"), "stage_id": st.get("id"), "stage_type": st.get("stage_type"),
                "stage_name": st.get("name") or (j.get("job") or {}).get("stage_name"), "active": None,
                "source": "applicant"}

    def event(self, applicant_id: int, body: str, job_id: int | None = None) -> dict:
        ev = {"applicant_id": applicant_id, "body": body, "type": "Event::Comment"}
        if job_id:
            ev["job_id"] = job_id
        return self._req("POST", "/events.json", {"event": ev})


def applicant_body(d: dict, *, vacancy_id: int | None) -> dict:
    tl = prof.test_line(d)
    year = (d["test"] or {}).get("date", "")[:4] or None
    cv = {"title": prof.title(d), "skills": prof.as_html(d), "about_me": prof.offer_text(d),
          "skill_set": prof.key_skills(d)}
    if tl:
        cv["education"] = {"attestation": [{"name": f"Адаптивный тест «Драфт»: {d['category_title'] or '—'}",
                                            "organization": d["platform"], "result": f"T1. {tl}", "year": year}]}
    if d["fsp"]["achievements"]:
        cv["awards"] = [{"name": a, "organization": "Федерация спортивного программирования",
                         "description": f"T2: подтверждено ({d['fsp']['source']})"} for a in d["fsp"]["achievements"]]
    if d["pdf_url"]:
        cv["certificate"] = [{"title": "Верифицированный профиль «Драфт» (PDF)", "url": d["pdf_url"],
                              "company": d["platform"]}]
    first = d["first_name"] if d["first_name"] and d["first_name"] != "—" else "Кандидат"
    a = {"first_name": first, "last_name": d["last_name"] or d["ref"], "middle_name": d["middle_name"],
         "emails": [d["email"]] if d["email"] else None,
         "phones": [prof.phone_digits(d["phone"])] if prof.phone_digits(d["phone"]) else None,
         "accounts": [{"url": f"https://t.me/{d['telegram']}", "icon_id": "telegram"}] if d["telegram"] else None,
         "source_type": "sourced", "source_url": get_isettings().public_base_url,
         "resumes": [{"cv_params": {k: v for k, v in cv.items() if v}}],
         # Список: объект {"body", "type"} (как в опубликованной спецификации) настоящий «Поток» отклоняет с 500
         # (проверено на API 07.10.2026), список из одного комментария — принимает
         "events": [{"body": prof.comment_text(d), "type": "Event::Comment"}],
         "ajs_joins": [{"job_id": vacancy_id}] if vacancy_id else None}
    return {k: v for k, v in a.items() if v not in (None, "", [])}


class PotokProvider(Provider):
    code, title = "potok", "Поток"

    def __init__(self, client: PotokClient):
        self.cl = client

    def check(self) -> dict:
        jobs = self.cl.jobs(per_page=100)
        return {"ok": True, "account": None, "vacancies_active": len(jobs),
                "details": [f"Токен действителен (GET /jobs.json → 200)", f"Активных вакансий: {len(jobs)}"]}

    def vacancies(self) -> list[dict]:
        return [{"id": j["id"], "title": j.get("name"),
                 "status": "archive" if j.get("archived") else (j.get("state_id") or "active"),
                 "department": (j.get("company_department") or {}).get("name"),
                 "salary": {"from": j.get("salary_from"), "to": j.get("salary_to"), "currency": j.get("currency_type")},
                 "stages": [{"id": s["id"], "title": s.get("name")} for s in j.get("stages") or []]}
                for j in self.cl.jobs(scope="all")]

    def stages(self, vacancy_id: int) -> list[dict]:
        j = self.cl.job(vacancy_id)
        return [{"id": s["id"], "title": s.get("name")} for s in sorted(j.get("stages") or [],
                                                                         key=lambda s: s.get("serial") or 0)]

    def push(self, d: dict, target: Target, link: LinkState, *, force: bool = False) -> dict:
        steps: list[str] = []
        vid, aid = target.vacancy_id, int(link.external_id) if link.external_id else None
        dedup, attached, join = ("link" if aid else None), False, None
        if aid is None:
            r = self.cl.create_applicant(applicant_body(d, vacancy_id=vid))
            aid = int(r["id"])
            join = next((j for j in r.get("ajs_joins") or [] if (j.get("job") or {}).get("id") == vid), None)
            link.save(external_id=aid, vacancy={"id": vid, "join_id": (join or {}).get("id"),
                                                "stage_id": ((join or {}).get("stage") or {}).get("id")} if vid else None)
            attached = bool(vid)
            steps.append(f"Создан кандидат (POST /applicants.json, id {aid})" + (f" на вакансии {vid}" if vid else "")
                         + ": резюме, тест T1, достижения ФСП T2, PDF-профиль")
        else:
            steps.append(f"Кандидат уже есть в «Потоке» (id {aid}) — новый не создаём")
            known = link.on_vacancy(vid)
            if vid and not known:
                join = self.cl.join(vid, aid)
                if join is None:
                    steps.append(f"Уже на вакансии {vid} (ответ 422 «кандидат на вакансии уже существует»)")
                    link.save(vacancy={"id": vid})
                else:
                    attached = True
                    link.save(vacancy={"id": vid, "join_id": join.get("id"),
                                       "stage_id": (join.get("stage") or {}).get("id")})
                    steps.append(f"Добавлен на вакансию {vid} (POST /ajs_joins.json)")
            elif vid:
                join = {"id": known.get("join_id"), "stage": {"id": known.get("stage_id")}}
                steps.append(f"Уже на вакансии {vid}" + (" — обновляем профиль" if force else " — повтор без изменений"))
        join_id = (join or {}).get("id") or (link.on_vacancy(vid) or {}).get("join_id")
        stage_now = ((join or {}).get("stage") or {}).get("id")
        if target.stage_id and join_id and (attached or force):
            if soft(steps, "Перевод на этап", lambda: self.cl.change_stage(join_id, target.stage_id) or True):
                stage_now = target.stage_id
                link.save(vacancy={**(link.on_vacancy(vid) or {"id": vid}), "stage_id": target.stage_id})
                steps.append(f"Переведён на этап «{target.stage_title or target.stage_id}» (change_stage)")
        if dedup and (attached or force):
            if soft(steps, "Комментарий", lambda: self.cl.event(aid, prof.comment_text(d, update=not attached), vid) or True):
                steps.append("Комментарий с вилкой оффера и ссылкой на PDF (POST /events.json)")
        stage_title = target.stage_title if (target.stage_id and stage_now == target.stage_id) else None
        if vid and stage_now and not stage_title:  # название этапа для карточки приглашения: «Передано: Поток · этап «Новые»»
            stage_title = (((join or {}).get("stage") or {}).get("name")
                           or soft(steps, "Название этапа", lambda: next(
                               (x["title"] for x in self.stages(vid) if x["id"] == stage_now), None)))
        url = CARD_URL.format(job=vid, stage=stage_now, applicant=aid) if (vid and stage_now and "app.potok.io"
                                                                           in self.cl.base) else None
        return {"external_id": aid, "applicant_id": aid, "vacancy_id": vid, "vacancy_title": target.vacancy_title,
                "join_id": join_id, "stage_id": target.stage_id if (attached or force) else None, "dedup": dedup,
                "stage_title": stage_title, "url": url, "steps": steps}
