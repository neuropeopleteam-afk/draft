"""Talantix (hh.ru): GraphQL API https://api.talantix.ru/graphql, документация https://api.talantix.ru/docs/.

Авторизация — OAuth 2.0: пару access/refresh токенов выпускает пользователь с ролью «Администратор» на тарифе
«Оптимальный» (личный кабинет → токены API; ссылка на JSON с токенами живёт 30 дней). Access-токен живёт 1 день,
refresh — 120 дней и одноразовый: после ``POST /oauth/token`` (grant_type=refresh_token) старый refresh-токен
больше не действует, новую пару сохраняем сразу (``on_tokens``). Проверка токена — ``GET /auth_check`` (204).
Обязательные заголовки: ``Authorization: Bearer``, ``Content-Type: application/json``, ``User-Agent`` (компания и
контакт — по нему Talantix свяжется при проблемах).

Ответы GraphQL: HTTP 200 / 210 (INTERNAL) / 269 (EXTERNAL_SYSTEM_ERROR), технические ошибки — в ``errors``,
предметные — типизированными объектами в ``data`` (union: ``PersonSaveError``, ``ResponsesCreatedError`` …).
В одном запросе — не больше одного корневого поля.

Схема: интроспекция ``POST /graphql/schema`` без токена недоступна (400 invalid_request), поэтому используемое
подмножество взято из справочника документации — docs/ats/talantix-schema.subset.graphql.

Передача кандидата:
1. ``persons(filter: {search: email, searchFrom: [CONTACTS]})`` — есть ли кандидат в базе (дубликат не создаём);
2. ``personSources(filterByName)`` / ``createPersonSource`` — источник «Встречный (ФСП)» (один раз на компанию);
3. ``dictionaries { areas }`` — areaId по городу кандидата (если нашёлся);
4. ``createPerson`` с ``vacancyIds``, ``contacts``, ``customResumes [{type: TMS, text: HTML профиля}]`` и
   ``structuredResume`` (title, link на PDF-профиль, skills, keySkills — подтверждённые навыки);
   кандидат из базы — ``createResponses(personIds, vacancyIds)`` на выбранную вакансию;
5. ``transferPersonsToWorkflowStatus`` — на выбранный этап (идемпотентно по документации);
6. ``createPersonComment`` на вакансии — вилка оффера, T1/T2 и ссылка на PDF.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import time
from typing import Callable

import httpx

from app.integrations.ats import clients as http
from app.integrations.ats import profile as prof
from app.integrations.ats.clients import AtsError, check_url
from app.integrations.ats.providers.base import LinkState, Provider, Target, soft
from app.integrations.settings import get_isettings

BASE_URL = "https://api.talantix.ru"
DOCS_URL = "https://api.talantix.ru/docs/"
SOURCE_NAME = "Встречный (ФСП)"

Q_ME = "query Me { me { id firstName lastName email } }"
Q_VACANCIES = """query Vacancies($first: Int, $after: String, $filter: VacancyFilterInput) {
  vacancies(first: $first, after: $after, filter: $filter) {
    count
    items { id title department status url salary { from to currency } }
    pageInfo { endCursor hasNextPage }
  }
}"""
Q_STAGES = """query VacancyStages($id: Int!) {
  vacancy(id: $id) {
    __typename
    ... on VacancyItem { id title workflowStatuses { items { id name position } } }
    ... on VacancyError { errorType message }
  }
}"""
Q_FIND = """query FindPerson($filter: PersonFilterInput) {
  persons(filter: $filter, first: 5) { items { id firstName lastName contacts { items { type value } } } }
}"""
Q_SOURCES = """query PersonSources($name: String) {
  personSources(filterByName: $name, first: 50) { items { id name } }
}"""
Q_AREAS = "query Areas { dictionaries { areas { items { id name parentId } } } }"
M_SOURCE = """mutation CreatePersonSource($name: String!) {
  createPersonSource(personSourceCreate: $name) {
    __typename
    ... on PersonSource { id name }
    ... on PersonSourceMutationError { errorType message }
  }
}"""
M_CREATE = """mutation CreatePerson($person: PersonCreateInput!) {
  createPerson(personCreate: $person) {
    __typename
    ... on PersonItem { id }
    ... on PersonSaveError { errorType message errors { field violatedConstraints } }
  }
}"""
M_RESPONSES = """mutation CreateResponses($personIds: [Int!]!, $vacancyIds: [Int!]!) {
  createResponses(personIds: $personIds, vacancyIds: $vacancyIds) {
    __typename
    ... on ResponsesCreatedSuccess { message }
    ... on ResponsesCreatedError { errorType message }
  }
}"""
M_TRANSFER = """mutation TransferPersons($personIds: [Int!]!, $statusId: Int!) {
  transferPersonsToWorkflowStatus(personIds: $personIds, workflowStatusId: $statusId) {
    __typename
    ... on PersonsToWorkflowStatusTransferredSuccess { message }
    ... on PersonsToWorkflowStatusTransferError { errorType message }
  }
}"""
M_COMMENT = """mutation CreatePersonComment($comment: PersonCommentCreateInput!) {
  createPersonComment(commentCreate: $comment) {
    __typename
    ... on Comment { id }
    ... on PersonCommentCreateError { errorType message }
  }
}"""

API_ACCESS = {"insufficient_permissions": "нет права использования API (нужен тариф «Оптимальный» и роль администратора)",
              "authorisation_not_found": "авторизация в Talantix истекла или отозвана — выпустите новые токены",
              "access_blocked": "доступ к API заблокирован, обратитесь в поддержку Talantix"}
_areas_cache: dict[str, tuple[float, dict[str, str]]] = {}


def user_agent() -> str:
    """Talantix требует User-Agent с названием компании и контактом для связи."""
    s = get_isettings()
    return f"Vstrechny-ATS/1.0 ({s.ats_user_agent_company}; {s.ats_user_agent_contact})"


def parse_tokens(raw: str | None, refresh: str | None = None) -> dict | None:
    """JSON со ссылки Talantix ({access_token, refresh_token, expires_in, created_at …}) или голый access-токен."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.startswith("{"):
        try:
            d = json.loads(raw)
        except ValueError:
            raise AtsError("Talantix: не удалось разобрать JSON с токенами") from None
        if not d.get("access_token"):
            raise AtsError("Talantix: в JSON нет access_token")
        return {"access_token": d["access_token"], "refresh_token": d.get("refresh_token") or refresh,
                "expires_at": _expiry(d.get("expires_in"), d.get("created_at")),
                "refresh_expires_at": _expiry(d.get("refresh_token_expires_in"), d.get("created_at"))}
    return {"access_token": raw, "refresh_token": (refresh or "").strip() or None, "expires_at": None,
            "refresh_expires_at": None}


def _expiry(seconds, created_ms=None) -> datetime | None:
    if not seconds:
        return None
    start = datetime.fromtimestamp(created_ms / 1000, timezone.utc) if created_ms else datetime.now(timezone.utc)
    return start + timedelta(seconds=int(seconds))


class TalantixClient:
    def __init__(self, base_url: str, access_token: str, refresh_token: str | None = None,
                 expires_at: datetime | None = None, on_tokens: Callable[[dict], None] | None = None,
                 timeout: float | None = None):
        self.base = check_url(base_url.rstrip("/"))
        self.access, self.refresh_token, self.expires_at = access_token, refresh_token, expires_at
        self.on_tokens = on_tokens
        self.timeout = timeout or get_isettings().ats_timeout_s
        self.refreshed = False

    # --- токены
    def refresh(self) -> dict:
        if not self.refresh_token:
            raise AtsError("Talantix: access-токен истёк, а refresh-токена нет — выпустите новую пару токенов", 401)
        try:
            r = http._send("POST", self.base + "/oauth/token", timeout=self.timeout,
                           data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
                           headers={"User-Agent": user_agent(), "Accept": "application/json",
                                    "Content-Type": "application/x-www-form-urlencoded"})
        except httpx.HTTPError as e:
            raise AtsError(f"Talantix недоступен ({type(e).__name__})") from None
        if r.status_code >= 400:
            err = _json(r).get("error")
            if err == "invalid_grant":
                raise AtsError("Talantix: refresh-токен недействителен, истёк или уже использован — "
                               "выпустите новую пару токенов в личном кабинете", 401)
            raise AtsError(f"Talantix: обновление токена — ответ {r.status_code} {err or ''}".strip(), r.status_code)
        d = _json(r)
        if not d.get("access_token"):
            raise AtsError("Talantix: в ответе oauth/token нет access_token", 502)
        self.access, self.refresh_token = d["access_token"], d.get("refresh_token") or self.refresh_token
        self.expires_at = _expiry(d.get("expires_in"))
        self.refreshed = True
        tok = {"access_token": self.access, "refresh_token": self.refresh_token, "expires_at": self.expires_at,
               "refresh_expires_at": _expiry(d.get("refresh_token_expires_in"))}
        if self.on_tokens:
            self.on_tokens(tok)  # refresh-токен одноразовый: новую пару сохраняем немедленно
        return tok

    def _maybe_refresh(self) -> None:
        if self.refresh_token and self.expires_at and datetime.now(timezone.utc) >= self.expires_at - timedelta(seconds=60):
            self.refresh()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access}", "User-Agent": user_agent(),
                "Content-Type": "application/json", "Accept": "application/json"}

    def _call(self, method: str, path: str, **kw) -> httpx.Response:
        self._maybe_refresh()
        for attempt in (1, 2):
            try:
                r = http._send(method, self.base + path, timeout=self.timeout, headers=self._headers(), **kw)
            except httpx.HTTPError as e:
                raise AtsError(f"Talantix недоступен ({type(e).__name__})") from None
            if r.status_code == 401 and attempt == 1 and self.refresh_token:
                self.refresh()  # token_expired / token_not_found после ротации — одна попытка с новой парой
                continue
            return r
        return r

    @staticmethod
    def _raise_http(r: httpx.Response) -> None:
        if r.status_code < 400:
            return
        d = _json(r)
        typ, det = d.get("type"), d.get("detail")
        if r.status_code == 401:
            what = "истёк" if det == "token_expired" else "не найден"
            raise AtsError(f"Talantix: access-токен {what} (401 {det or typ or ''})".strip(), 401)
        if r.status_code == 403:
            raise AtsError(f"Talantix: {API_ACCESS.get(det, det or 'доступ запрещён')} (403)", 403)
        if r.status_code == 429:
            raise AtsError("Talantix: превышен лимит запросов (429)", 429)
        if r.status_code == 400:
            raise AtsError(f"Talantix: некорректный запрос (400 {det or typ or ''})".strip(), 400)
        raise AtsError(f"Talantix ответил {r.status_code}", r.status_code)

    def auth_check(self) -> None:
        r = self._call("GET", "/auth_check")
        self._raise_http(r)

    def gql(self, query: str, variables: dict | None = None) -> dict:
        r = self._call("POST", "/graphql", json={"query": query, "variables": variables or {}})
        self._raise_http(r)
        body = _json(r)
        errors = body.get("errors") or []
        if errors:
            types = {(e.get("extensions") or {}).get("errorType") for e in errors}
            msg = (errors[0].get("message") or "ошибка")[:200]
            if types & {"INTERNAL", "EXTERNAL_SYSTEM_ERROR"} or r.status_code in (210, 269):
                if not body.get("dataPresent") and not body.get("data"):
                    raise AtsError(f"Talantix: внутренняя ошибка ({msg})", 503)
            else:
                raise AtsError(f"Talantix: запрос отклонён ({msg})", 400)
        return body.get("data") or {}

    # --- операции
    def me(self) -> dict:
        return self.gql(Q_ME).get("me") or {}

    def vacancies(self, status: str | None = "ACTIVE", limit: int = 200) -> list[dict]:
        out, after = [], None
        while len(out) < limit:
            v = self.gql(Q_VACANCIES, {"first": min(200, limit - len(out)), "after": after,
                                       "filter": {"vacancyStatus": status} if status else None}).get("vacancies") or {}
            out += v.get("items") or []
            page = v.get("pageInfo") or {}
            if not page.get("hasNextPage") or not page.get("endCursor"):
                break
            after = page["endCursor"]
        return out

    def stages(self, vacancy_id: int) -> list[dict]:
        v = self.gql(Q_STAGES, {"id": vacancy_id}).get("vacancy") or {}
        if v.get("__typename") == "VacancyError":
            raise AtsError(f"Talantix: вакансия {vacancy_id} — {v.get('errorType')}", 404)
        items = (v.get("workflowStatuses") or {}).get("items") or []
        return sorted([s for s in items if s], key=lambda s: s.get("position") or 0)

    def find_person(self, email: str | None) -> int | None:
        if not email:
            return None
        items = (self.gql(Q_FIND, {"filter": {"search": email, "searchFrom": ["CONTACTS"]}}).get("persons") or {}) \
            .get("items") or []
        for p in items:
            for c in ((p or {}).get("contacts") or {}).get("items") or []:
                if c.get("type") == "email" and (c.get("value") or "").strip().lower() == email.strip().lower():
                    return int(p["id"])
        return None

    def source_id(self, name: str = SOURCE_NAME) -> int | None:
        items = (self.gql(Q_SOURCES, {"name": name}).get("personSources") or {}).get("items") or []
        hit = next((s for s in items if (s.get("name") or "").strip().lower() == name.lower()), None)
        if hit:
            return int(hit["id"])
        r = self.gql(M_SOURCE, {"name": name}).get("createPersonSource") or {}
        if r.get("__typename") == "PersonSourceMutationError" or not r.get("id"):
            raise AtsError(f"Talantix: источник не создан ({r.get('errorType')})", 422)
        return int(r["id"])

    def area_id(self, city: str | None) -> str | None:
        if not city:
            return None
        cached = _areas_cache.get(self.base)
        if not cached or time.time() - cached[0] > 86400:
            items = ((self.gql(Q_AREAS).get("dictionaries") or {}).get("areas") or {}).get("items") or []
            cached = (time.time(), {(a.get("name") or "").strip().lower(): a["id"] for a in items
                                    if a.get("parentId")})  # города; страны (parentId = null) — гражданства
            _areas_cache[self.base] = cached
        return cached[1].get(city.strip().lower())

    def create_person(self, person: dict) -> int:
        r = self.gql(M_CREATE, {"person": person}).get("createPerson") or {}
        if r.get("__typename") == "PersonSaveError" or not r.get("id"):
            fields = ", ".join(f"{e.get('field')}: {'/'.join(e.get('violatedConstraints') or [])}"
                               for e in r.get("errors") or [])
            raise AtsError(f"Talantix: кандидат не сохранён ({r.get('errorType') or 'ошибка'}"
                           f"{'; ' + fields if fields else ''})", 403 if r.get("errorType") == "ACCESS_DENIED" else 422)
        return int(r["id"])

    def create_responses(self, person_ids: list[int], vacancy_ids: list[int]) -> None:
        r = self.gql(M_RESPONSES, {"personIds": person_ids, "vacancyIds": vacancy_ids}).get("createResponses") or {}
        if r.get("__typename") == "ResponsesCreatedError" or r.get("errorType"):
            raise AtsError(f"Talantix: кандидат не добавлен на вакансию ({r.get('errorType')})", 422)

    def transfer(self, person_ids: list[int], status_id: int) -> None:
        r = self.gql(M_TRANSFER, {"personIds": person_ids, "statusId": status_id}) \
            .get("transferPersonsToWorkflowStatus") or {}
        if r.get("__typename") == "PersonsToWorkflowStatusTransferError" or r.get("errorType"):
            raise AtsError(f"Talantix: перевод на этап не выполнен ({r.get('errorType')})", 422)

    def comment(self, person_id: int, text: str, vacancy_id: int | None = None) -> int | None:
        c = {"personId": person_id, "text": text, "commentVisibility": {"visibleForAll": True}}
        if vacancy_id:
            c["vacancyId"] = vacancy_id
        r = self.gql(M_COMMENT, {"comment": c}).get("createPersonComment") or {}
        if r.get("__typename") == "PersonCommentCreateError" or r.get("errorType"):
            raise AtsError(f"Talantix: комментарий не добавлен ({r.get('errorType')})", 422)
        return r.get("id")


def _json(r: httpx.Response) -> dict:
    try:
        d = r.json()
        return d if isinstance(d, dict) else {"data": d}
    except ValueError:
        return {}


def person_input(d: dict, *, vacancy_id: int | None, source_id: int | None, area_id: str | None) -> dict:
    """PersonCreateInput: ФИО, контакты, резюме TMS (HTML профиля) и structuredResume (title, link, skills)."""
    contacts = []
    if d["email"]:
        contacts.append({"type": "email", "value": d["email"]})
    if d["phone"]:
        contacts.append({"type": "cell", "value": d["phone"]})
    if d["telegram"]:
        contacts.append({"type": "telegram", "value": d["telegram"]})
    first = d["first_name"] if d["first_name"] and d["first_name"] != "—" else "Кандидат"
    person = {"firstName": first, "lastName": d["last_name"] or d["ref"], "middleName": d["middle_name"],
              "contacts": contacts, "customResumes": [{"type": "TMS", "text": prof.as_html(d)}],
              "structuredResume": {"title": prof.title(d), "link": d["pdf_url"] or d["card_url"],
                                   "skills": prof.as_text(d)[:4000], "keySkills": prof.key_skills(d)},
              "sourceId": source_id, "areaId": area_id, "vacancyIds": [vacancy_id] if vacancy_id else None}
    return {k: v for k, v in person.items() if v not in (None, "", [])}


class TalantixProvider(Provider):
    code, title = "talantix", "Talantix"

    def __init__(self, client: TalantixClient, *, source_id: int | None = None,
                 on_source: Callable[[int], None] | None = None):
        self.cl = client
        self.source_cached, self.on_source = source_id, on_source

    def check(self) -> dict:
        self.cl.auth_check()
        me = self.cl.me()
        vac = self.cl.vacancies(limit=200)
        name = " ".join(x for x in (me.get("firstName"), me.get("lastName")) if x)
        return {"ok": True, "account": name or me.get("email"), "account_id": me.get("id"),
                "vacancies_active": len(vac), "token_refreshed": self.cl.refreshed,
                "token_expires_at": self.cl.expires_at.isoformat() if self.cl.expires_at else None,
                "details": [f"Токен действителен (GET /auth_check → 204), владелец: {name or me.get('email') or me.get('id')}",
                            f"Активных вакансий: {len(vac)}"]}

    def vacancies(self) -> list[dict]:
        return [{"id": v["id"], "title": v.get("title"), "status": (v.get("status") or "").lower(),
                 "department": v.get("department"), "url": v.get("url"),
                 "salary": v.get("salary")} for v in self.cl.vacancies(status=None)]

    def stages(self, vacancy_id: int) -> list[dict]:
        return [{"id": s["id"], "title": s.get("name")} for s in self.cl.stages(vacancy_id)]

    def _source(self, steps: list[str]) -> int | None:
        if self.source_cached:
            return self.source_cached
        sid = soft(steps, "Источник «Встречный (ФСП)»", self.cl.source_id)
        if sid:
            self.source_cached = sid
            if self.on_source:
                self.on_source(sid)
        return sid

    def push(self, d: dict, target: Target, link: LinkState, *, force: bool = False) -> dict:
        steps: list[str] = []
        vid, pid, dedup = target.vacancy_id, int(link.external_id) if link.external_id else None, None
        if pid:
            dedup = "link"
            steps.append(f"Кандидат уже есть в Talantix (id {pid}) — новый не создаём")
        else:
            pid = self.cl.find_person(d["email"])
            if pid:
                dedup = "remote"
                link.save(external_id=pid)
                steps.append(f"Найден в базе Talantix по почте (persons, id {pid}) — дубликат не создаём")
        attached = False
        if pid is None:
            sid = self._source(steps)
            area = soft(steps, "Город (справочник areas)", lambda: self.cl.area_id(d["declared"]["city"]))
            pid = self.cl.create_person(person_input(d, vacancy_id=vid, source_id=sid, area_id=area))
            link.save(external_id=pid, vacancy={"id": vid} if vid else None)
            attached = bool(vid)
            steps.append(f"Создан кандидат (createPerson, id {pid})" + (f" на вакансии {vid}" if vid else "")
                         + " с резюме TMS и structuredResume")
        elif vid and not link.on_vacancy(vid):
            self.cl.create_responses([pid], [vid])
            link.save(vacancy={"id": vid})
            attached = True
            steps.append(f"Добавлен на вакансию {vid} (createResponses)")
        elif vid:
            steps.append(f"Уже на вакансии {vid}" + (" — обновляем профиль" if force else " — повтор без изменений"))
        if target.stage_id and (attached or force):
            if soft(steps, "Перевод на этап", lambda: self.cl.transfer([pid], target.stage_id) or True):
                steps.append(f"Переведён на этап «{target.stage_title or target.stage_id}» (transferPersonsToWorkflowStatus)")
        if attached or force or dedup == "remote":
            # кандидату из базы резюме не перезаписываем: полный профиль — комментарием на вакансии
            text = prof.as_html(d) if dedup == "remote" else prof.comment_text(d, update=force and not attached)
            if soft(steps, "Комментарий", lambda: self.cl.comment(pid, text, vid) or True):
                steps.append("Комментарий: вилка оффера, T1/T2 и ссылка на PDF (createPersonComment)")
        return {"external_id": pid, "person_id": pid, "vacancy_id": vid, "vacancy_title": target.vacancy_title,
                "stage_id": target.stage_id if (attached or force) else None, "dedup": dedup,
                "token_refreshed": self.cl.refreshed, "steps": steps}
