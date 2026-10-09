"""Демо-заглушки Talantix и «Потока»: имитируют их API по настоящему HTTP, чтобы жюри видело сценарий без
реальных токенов. Платформа ходит к ним тем же клиентом, что и к настоящим системам, — меняется только адрес.

Talantix (``/api/ats-stub/talantix``) — как https://api.talantix.ru:
* ``GET /auth_check`` — 204 или 401 ``{"type": "invalid_token", "detail": "token_expired" | "token_not_found"}``;
* ``POST /oauth/token`` (form: grant_type=refresh_token) — новая пара, refresh одноразовый (400 invalid_grant);
* ``POST /graphql`` — обязательны User-Agent и Bearer, одно корневое поле; me, vacancies, vacancy, persons,
  personSources, createPersonSource, createPerson (валидация как PersonSaveError), createResponses,
  transferPersonsToWorkflowStatus, createPersonComment, dictionaries.areas. Ответ ``{"data", "errors", "dataPresent"}``.
  Access-токен демо живёт 15 минут — автоматическое обновление по refresh-токену видно в журнале.

«Поток» (``/api/ats-stub/potok/api/v3``) — как https://app.potok.io/api/v3: ``GET /jobs.json``, ``GET /jobs/{id}.json``,
``POST /applicants.json`` (``events`` — только список, объект → 500, как у настоящего «Потока»),
``GET /applicants/{id}.json``, ``POST /ajs_joins.json`` (422 при повторе), ``POST /ajs_joins/{id}/change_stage.json``,
``POST /events.json``; для обратного канала — ``GET /jobs/{id}/ajs_joins.json?applicant_id=`` (этап и признак
активности) и ``POST /jobs/{id}/{applicant}/decline.json``; рекрутёр демо-«Потока» двигает кандидата по этапам из
кабинета (``potok_demo_move``). Токен — Bearer или ``?token=``.

Всё, что пришло, хранится в ats_stub_records ящика компании и видно работодателю в «Тестовая ATS: что пришло».
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import re
import secrets

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db, utcnow
from app.integrations.ats.models import AtsSettings, AtsStubRecord

router = APIRouter(prefix="/api/ats-stub", tags=["ats-stub"])
INTERNAL_KINDS = ("talantix_token", "talantix_source")
TX_ACCESS_TTL = 900
TX_REFRESH_TTL = 10368000  # 120 дней, как у Talantix
_STAGES = [("Новые", "sourced"), ("Первичный контакт", "applied"), ("Интервью", "interview"), ("Оффер", "offer"),
           ("Вышел на работу", "hired")]


def _vac(vid: int, title: str, dept: str, status: str, sfrom: int, sto: int, city: str) -> dict:
    return {"id": vid, "title": title, "department": dept, "status": status, "city": city,
            "salary": {"from": sfrom, "to": sto, "currency": "RUR"},
            "stages": [{"id": vid * 10 + i, "name": n, "position": i, "stage_type": t}
                       for i, (n, t) in enumerate(_STAGES, 1)]}


DEMO_VACANCIES = [
    _vac(410101, "Backend-разработчик (платежи)", "Платёжная платформа", "ACTIVE", 240000, 280000, "Москва"),
    _vac(410102, "Python-разработчик (интеграции)", "Интеграции", "ACTIVE", 200000, 260000, "Москва"),
    _vac(410103, "Frontend-разработчик (React)", "Личный кабинет", "ACTIVE", 180000, 240000, "Санкт-Петербург"),
    _vac(410104, "Аналитик данных", "Аналитика", "ARCHIVE", 160000, 220000, "Казань"),
]
AREAS = [{"id": "113", "name": "Россия", "parentId": None}, {"id": "1", "name": "Москва", "parentId": "113"},
         {"id": "2", "name": "Санкт-Петербург", "parentId": "113"}, {"id": "3", "name": "Екатеринбург", "parentId": "113"},
         {"id": "4", "name": "Новосибирск", "parentId": "113"}, {"id": "88", "name": "Казань", "parentId": "113"},
         {"id": "66", "name": "Нижний Новгород", "parentId": "113"}]
TX_SOURCES = [{"id": 481, "name": "Сайт компании"}, {"id": 506, "name": "Рекомендация"}]
CONTACT_TYPES = {"cell", "email", "facebook", "freelance", "habr", "home", "icq", "linkedin", "livejournal",
                 "personal", "skype", "telegram", "vk", "work"}


def kind_system(kind: str) -> str:
    return {"huntflow": "Хантфлоу", "talantix": "Talantix", "potok": "Поток"}.get(kind.split("_")[0], "Вебхук")


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _new_id() -> int:
    return 1_000_000 + secrets.randbelow(8_999_999)


def _records(db: Session, key: str, kind: str) -> list[AtsStubRecord]:
    return list(db.scalars(select(AtsStubRecord).where(AtsStubRecord.stub_key == key, AtsStubRecord.kind == kind)
                           .order_by(AtsStubRecord.created_at)).all())


def _box_exists(db: Session, key: str) -> bool:
    return bool(key) and db.scalar(select(AtsSettings.company_id).where(AtsSettings.stub_key == key)) is not None


# ------------------------------------------------------------------ Talantix

def talantix_issue(db: Session, stub_key: str) -> dict:
    """Пара токенов демо-Talantix — тот же JSON, что отдаёт ссылка из личного кабинета Talantix."""
    access, refresh = f"txa.{stub_key}.{secrets.token_urlsafe(18)}", f"txr.{stub_key}.{secrets.token_urlsafe(18)}"
    now = utcnow().timestamp()
    db.add(AtsStubRecord(stub_key=stub_key, kind="talantix_token", payload={
        "a": _h(access), "r": _h(refresh), "a_exp": now + TX_ACCESS_TTL, "r_exp": now + TX_REFRESH_TTL, "used": False}))
    db.flush()
    return {"name": "Встречный (демо)", "access_token": access, "expires_in": TX_ACCESS_TTL, "refresh_token": refresh,
            "refresh_token_expires_in": TX_REFRESH_TTL, "token_type": "bearer", "created_at": int(now * 1000)}


def _tx_err(status: int, typ: str, detail: str) -> JSONResponse:
    return JSONResponse({"type": typ, "detail": detail}, status_code=status)


def _tx_auth(db: Session, authorization: str | None) -> tuple[str | None, JSONResponse | None]:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        return None, _tx_err(400, "invalid_request", "authorization_header_not_found")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "txa" or not _box_exists(db, parts[1]):
        return None, _tx_err(401, "invalid_token", "token_not_found")
    rec = next((r for r in _records(db, parts[1], "talantix_token") if r.payload.get("a") == _h(token)), None)
    if rec is None:
        return None, _tx_err(401, "invalid_token", "token_not_found")
    if rec.payload.get("used") or rec.payload["a_exp"] < utcnow().timestamp():
        return None, _tx_err(401, "invalid_token", "token_expired")
    return parts[1], None


@router.get("/talantix/auth_check", summary="Демо-Talantix: проверка токена (204)", status_code=204)
def tx_auth_check(authorization: str | None = Header(None), user_agent: str | None = Header(None),
                  db: Session = Depends(get_db)):
    if not user_agent:
        return _tx_err(400, "invalid_request", "user_agent_required")
    _, err = _tx_auth(db, authorization)
    return err or Response(status_code=204)


@router.post("/talantix/oauth/token", summary="Демо-Talantix: обновление пары токенов по refresh_token")
async def tx_oauth(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    if form.get("grant_type") != "refresh_token":
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
    refresh = str(form.get("refresh_token") or "")
    parts = refresh.split(".")
    if len(parts) != 3 or parts[0] != "txr" or not _box_exists(db, parts[1]):
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    rec = next((r for r in _records(db, parts[1], "talantix_token") if r.payload.get("r") == _h(refresh)), None)
    if rec is None or rec.payload.get("used") or rec.payload["r_exp"] < utcnow().timestamp():
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    rec.payload = {**rec.payload, "used": True}  # refresh-токен одноразовый, старый access тоже гасим
    tok = talantix_issue(db, parts[1])
    db.commit()
    return tok


ROOT_RE = re.compile(r"^\s*(?:(query|mutation)\b[^{]*)?\{\s*(\w+)", re.S)


def _gql(data=None, errors=None, status: int = 200) -> JSONResponse:
    return JSONResponse({"data": data, "errors": errors or [], "dataPresent": data is not None}, status_code=status)


def _gql_error(message: str, error_type: str = "ValidationError") -> JSONResponse:
    return _gql(None, [{"message": message, "locations": [], "extensions": {"classification": error_type,
                                                                           "errorType": error_type}}])


def _vacancy(vid) -> dict | None:
    return next((v for v in DEMO_VACANCIES if v["id"] == vid), None)


def _tx_vacancy_out(v: dict) -> dict:
    return {"__typename": "VacancyItem", "id": v["id"], "title": v["title"], "department": v["department"],
            "status": v["status"], "url": None, "salary": v["salary"],
            "workflowStatuses": {"items": [{"id": s["id"], "name": s["name"], "position": s["position"]}
                                           for s in v["stages"]]}}


def _tx_persons(db: Session, key: str) -> list[AtsStubRecord]:
    return _records(db, key, "talantix_person")


def _save_error(field: str, constraint: str, message: str) -> dict:
    return {"__typename": "PersonSaveError", "errorType": "VALIDATION", "message": message,
            "errors": [{"field": field, "violatedConstraints": [constraint]}]}


def _tx_create_person(db: Session, key: str, p: dict) -> dict:
    if not (p.get("firstName") or "").strip():
        return _save_error("firstName", "NotBlank", "firstName обязателен")
    for c in p.get("contacts") or []:
        if c.get("type") not in CONTACT_TYPES or not (c.get("value") or "").strip():
            return _save_error("contacts", "AllowedValues", f"Недопустимый контакт {c.get('type')}")
    for r in p.get("customResumes") or []:
        if r.get("type") != "TMS" or not (r.get("text") or "").strip():
            return _save_error("customResumes", "AllowedValues", "Резюме: type TMS и непустой text")
    for vid in p.get("vacancyIds") or []:
        v = _vacancy(vid)
        if v is None or v["status"] != "ACTIVE":
            return _save_error("vacancyIds", "AllowedValues", f"Вакансия {vid} не найдена или в архиве")
    if p.get("areaId") and p["areaId"] not in {a["id"] for a in AREAS}:
        return _save_error("areaId", "AllowedValues", "Неизвестный регион")
    sources = {s["id"] for s in TX_SOURCES} | {r.external_id for r in _records(db, key, "talantix_source")}
    if p.get("sourceId") and p["sourceId"] not in sources:
        return _save_error("sourceId", "AllowedValues", "Неизвестный источник")
    pid = _new_id()
    db.add(AtsStubRecord(stub_key=key, kind="talantix_person", external_id=pid, payload=p))
    db.commit()
    return {"__typename": "PersonItem", "id": pid}


def _tx_resolve(db: Session, key: str, root: str, v: dict):  # noqa: C901 — диспетчер полей заглушки
    if root == "me":
        return {"id": 7219, "firstName": "Демо", "lastName": "Администратор", "email": "admin@talantix.demo"}
    if root == "vacancies":
        status = (v.get("filter") or {}).get("vacancyStatus")
        items = [_tx_vacancy_out(x) for x in DEMO_VACANCIES if not status or x["status"] == status]
        first = min(int(v.get("first") or 20), 200)
        return {"count": len(items), "items": items[:first],
                "pageInfo": {"endCursor": None, "hasNextPage": False}}
    if root == "vacancy":
        x = _vacancy(v.get("id"))
        return _tx_vacancy_out(x) if x else {"__typename": "VacancyError", "errorType": "NOT_FOUND",
                                             "message": "Вакансия не найдена"}
    if root == "persons":
        q = ((v.get("filter") or {}).get("search") or "").strip().lower()
        items = []
        for r in _tx_persons(db, key):
            contacts = r.payload.get("contacts") or []
            if q and any(q == (c.get("value") or "").strip().lower() for c in contacts):
                items.append({"id": r.external_id, "firstName": r.payload.get("firstName"),
                              "lastName": r.payload.get("lastName"), "contacts": {"items": contacts}})
        return {"items": items[: int(v.get("first") or 20)]}
    if root == "personSources":
        name = (v.get("name") or v.get("filterByName") or "").strip().lower()
        own = [{"id": r.external_id, "name": r.payload.get("name")} for r in _records(db, key, "talantix_source")]
        return {"items": [s for s in TX_SOURCES + own if not name or name in s["name"].lower()]}
    if root == "createPersonSource":
        name = (v.get("name") or "").strip()
        if not 1 <= len(name) <= 100:
            return {"__typename": "PersonSourceMutationError", "errorType": "MAX_LENGTH" if name else "MIN_LENGTH",
                    "message": "Длина названия источника"}
        sid = _new_id()
        db.add(AtsStubRecord(stub_key=key, kind="talantix_source", external_id=sid, payload={"name": name}))
        db.commit()
        return {"__typename": "PersonSource", "id": sid, "name": name}
    if root == "createPerson":
        return _tx_create_person(db, key, v.get("person") or v.get("personCreate") or {})
    if root == "createResponses":
        pids, vids = v.get("personIds") or [], v.get("vacancyIds") or []
        known = {r.external_id for r in _tx_persons(db, key)}
        if not pids or any(p not in known for p in pids) or any(_vacancy(x) is None for x in vids):
            return {"__typename": "ResponsesCreatedError", "errorType": "VALIDATION", "message": "Нет кандидата или вакансии"}
        db.add(AtsStubRecord(stub_key=key, kind="talantix_response", external_id=pids[0],
                             payload={"personIds": pids, "vacancyIds": vids,
                                      "vacancyTitles": [_vacancy(x)["title"] for x in vids]}))
        db.commit()
        return {"__typename": "ResponsesCreatedSuccess", "message": "Отклики созданы"}
    if root == "transferPersonsToWorkflowStatus":
        sid = v.get("statusId") or v.get("workflowStatusId")
        stage = next((s for x in DEMO_VACANCIES for s in x["stages"] if s["id"] == sid), None)
        if stage is None:
            return {"__typename": "PersonsToWorkflowStatusTransferError", "errorType": "NOT_FOUND",
                    "message": "Этап не найден"}
        db.add(AtsStubRecord(stub_key=key, kind="talantix_transfer", external_id=(v.get("personIds") or [None])[0],
                             payload={"personIds": v.get("personIds"), "workflowStatusId": sid,
                                      "statusName": stage["name"]}))
        db.commit()
        return {"__typename": "PersonsToWorkflowStatusTransferredSuccess", "message": "Переведены"}
    if root == "createPersonComment":
        c = v.get("comment") or v.get("commentCreate") or {}
        if not c.get("personId") or not (c.get("text") or "").strip() or "commentVisibility" not in c:
            return {"__typename": "PersonCommentCreateError", "errorType": "VALIDATION", "message": "Нет текста"}
        cid = _new_id()
        db.add(AtsStubRecord(stub_key=key, kind="talantix_comment", external_id=c["personId"],
                             payload={**c, "commentId": cid}))
        db.commit()
        return {"__typename": "Comment", "id": cid}
    if root == "dictionaries":
        return {"areas": {"items": AREAS}}
    return None


@router.post("/talantix/graphql", summary="Демо-Talantix: GraphQL (одно корневое поле на запрос)")
async def tx_graphql(request: Request, authorization: str | None = Header(None),
                     user_agent: str | None = Header(None), db: Session = Depends(get_db)):
    if not user_agent:
        return _tx_err(400, "invalid_request", "user_agent_required")
    key, err = _tx_auth(db, authorization)
    if err:
        return err
    try:
        body = await request.json()
    except ValueError:
        body = {}
    query = (body or {}).get("query") if isinstance(body, dict) else None
    if not query:
        return _tx_err(400, "invalid_request", "graphql_query_not_found")
    m = ROOT_RE.match(query)
    if not m:
        return _gql_error("Invalid Syntax", "InvalidSyntax")
    root = m.group(2)
    data = _tx_resolve(db, key, root, body.get("variables") or {})
    if data is None:
        return _gql_error(f"Validation error (FieldUndefined@[{root}]) : Field '{root}' in type is undefined")
    return _gql({root: data})


def talantix_expire_access(db: Session, stub_key: str) -> int:
    """Для демо и тестов: «состарить» все access-токены ящика (refresh остаётся рабочим)."""
    n = 0
    for r in _records(db, stub_key, "talantix_token"):
        r.payload = {**r.payload, "a_exp": utcnow().timestamp() - 1}
        n += 1
    db.flush()
    return n


# ------------------------------------------------------------------ «Поток»

def potok_token(stub_key: str) -> str:
    return f"ptk.{stub_key}"


def _pt_key(db: Session, authorization: str | None, token: str | None) -> str | None:
    t = (authorization or "").removeprefix("Bearer ").strip() or (token or "").strip()
    if not t.startswith("ptk."):
        return None
    key = t[4:]
    return key if _box_exists(db, key) else None


def _pt_401() -> JSONResponse:
    return JSONResponse({"errors": "Неверный токен"}, status_code=401)


# Типы этапов «Потока» (в спецификации: applied, sourced, screening, interview_client, offer, accepted)
_PT_TYPES = {"interview": "interview_client", "hired": "accepted"}


def _pt_type(t: str) -> str:
    return _PT_TYPES.get(t, t)


# Поля вакансии «Потока», которых нет у Talantix: описание (HTML), опыт и график (справочники как в hh.ru), навыки —
# как в ответе настоящего GET /jobs.json (проверено 09.10.2026); по ним работает импорт вакансий (И23)
PT_JOB_DETAILS = {
    410101: {"description": "<p>Ищем Middle Backend-разработчика в команду платёжной платформы.</p>"
                            "<p><b>Требования:</b> Python, FastAPI, PostgreSQL, Redis; будет плюсом Kafka.</p>"
                            "<p>Обязанности: API платежей, интеграции с банками, код-ревью.</p>",
             "experience_type": "between3And6", "schedule_type": "fullDay", "key_skills": ["Python", "FastAPI"]},
    410102: {"description": "<p>Python-разработчик в команду интеграций: обмен с партнёрами по REST и очередям.</p>"
                            "<ul><li>Python, Django, PostgreSQL</li><li>Docker, Git</li></ul>",
             "experience_type": "between1And3", "schedule_type": "remote", "key_skills": []},
    410103: {"description": "<p>Frontend-разработчик уровня Middle: React, TypeScript, личный кабинет клиента.</p>",
             "experience_type": "between3And6", "schedule_type": "fullDay", "key_skills": ["React", "TypeScript"]},
    410104: {"description": "<p>Аналитик данных: SQL, Python, дашборды для продуктовых команд.</p>",
             "experience_type": "between1And3", "schedule_type": "fullDay", "key_skills": ["SQL"]},
}
_AREA_ID = {a["name"]: a["id"] for a in AREAS}


def _pt_job(j: dict) -> dict:
    return {"id": j["id"], "name": j["title"], "state_id": "closed" if j["status"] != "ACTIVE" else "opened",
            "archived": j["status"] != "ACTIVE", "company_department": {"id": j["id"] // 100, "name": j["department"]},
            "salary_from": j["salary"]["from"], "salary_to": j["salary"]["to"], "currency_type": "RUR",
            "city": _AREA_ID.get(j["city"], j["city"]), "employment_type": "full",
            **PT_JOB_DETAILS.get(j["id"], {"description": "", "key_skills": []}),
            "stages": [{"id": s["id"], "name": s["name"], "serial": s["position"],
                        "stage_type": _pt_type(s["stage_type"])} for s in j["stages"]]}


def _stage_obj(j: dict, stage_type: str = "sourced") -> dict:
    s = next((s for s in j["stages"] if s["stage_type"] == stage_type), j["stages"][0])
    return {"id": s["id"], "name": s["name"], "stage_type": _pt_type(s["stage_type"])}


@router.get("/potok/api/v3/jobs.json", summary="Демо-«Поток»: список вакансий")
def pt_jobs(by_scope: str = "active", page: int = 1, per_page: int = 50, token: str | None = None,
            authorization: str | None = Header(None), db: Session = Depends(get_db)):
    if _pt_key(db, authorization, token) is None:
        return _pt_401()
    jobs = [j for j in DEMO_VACANCIES if by_scope == "all" or j["status"] == "ACTIVE"]
    chunk = jobs[(page - 1) * per_page: page * per_page]
    return {"data": [_pt_job(j) for j in chunk]}


@router.get("/potok/api/v3/jobs/{job_id}.json", summary="Демо-«Поток»: вакансия с этапами")
def pt_job(job_id: int, token: str | None = None, authorization: str | None = Header(None),
           db: Session = Depends(get_db)):
    if _pt_key(db, authorization, token) is None:
        return _pt_401()
    j = _vacancy(job_id)
    return _pt_job(j) if j else JSONResponse({"errors": "Not found"}, status_code=404)


def _pt_joins(db: Session, key: str) -> list[AtsStubRecord]:
    return _records(db, key, "potok_join")


def _pt_add_join(db: Session, key: str, job: dict, applicant_id: int, stage_type: str = "sourced") -> dict:
    jid, stage = _new_id(), _stage_obj(job, stage_type)
    db.add(AtsStubRecord(stub_key=key, kind="potok_join", external_id=jid,
                         payload={"job_id": job["id"], "job_name": job["title"], "applicant_id": applicant_id,
                                  "stage_id": stage["id"], "stage_name": stage["name"], "active": True,
                                  "created_at": utcnow().isoformat()}))
    return {"id": jid, "job": {"id": job["id"], "name": job["title"]}, "stage": stage,
            "applicant": {"id": applicant_id}}


PHONE_RE = re.compile(r"^\d{11,15}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/potok/api/v3/applicants.json", summary="Демо-«Поток»: создать кандидата (можно сразу на вакансии)")
async def pt_create_applicant(request: Request, token: str | None = None, authorization: str | None = Header(None),
                              db: Session = Depends(get_db)):
    key = _pt_key(db, authorization, token)
    if key is None:
        return _pt_401()
    a = ((await request.json()) or {}).get("applicant") or {}
    events = a.get("events")
    if events is not None and not isinstance(events, list):  # как настоящий «Поток»: events — только список
        return JSONResponse({"status": 500, "error": "Internal Server Error"}, status_code=500)
    errors: dict[str, list[str]] = {}
    if not (a.get("first_name") or a.get("last_name")):
        errors["name"] = ["не может быть пустым"]
    if any(not PHONE_RE.match(str(p)) for p in a.get("phones") or []):
        errors["phones"] = ["телефон с кодом страны, только цифры"]
    if any(not EMAIL_RE.match(str(e)) for e in a.get("emails") or []):
        errors["emails"] = ["имеет неверное значение"]
    if a.get("source_type") not in (None, "sourced", "applied"):
        errors["source_type"] = ["имеет неверное значение"]
    jobs = [_vacancy(j.get("job_id")) for j in a.get("ajs_joins") or []]
    if any(j is None or j["status"] != "ACTIVE" for j in jobs):
        errors["ajs_joins"] = ["вакансия не найдена"]
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    aid = _new_id()
    joins = [_pt_add_join(db, key, j, aid, a.get("source_type") or "sourced") for j in jobs]
    db.add(AtsStubRecord(stub_key=key, kind="potok_applicant", external_id=aid,
                         payload={**a, "ajs_joins": [{"job_id": j["job"]["id"], "job_name": j["job"]["name"],
                                                      "stage": j["stage"]["name"]} for j in joins]}))
    for ev in events or []:
        if isinstance(ev, dict) and ev.get("body"):
            db.add(AtsStubRecord(stub_key=key, kind="potok_event", external_id=aid, payload={"applicant_id": aid, **ev}))
    db.commit()
    return {"id": aid, "first_name": a.get("first_name"), "last_name": a.get("last_name"),
            "middle_name": a.get("middle_name"), "emails": a.get("emails") or [], "phones": a.get("phones") or [],
            "source_type": a.get("source_type"), "created_at": utcnow().isoformat(), "ajs_joins": joins}


@router.get("/potok/api/v3/applicants/{applicant_id}.json", summary="Демо-«Поток»: кандидат")
def pt_applicant(applicant_id: int, token: str | None = None, authorization: str | None = Header(None),
                 db: Session = Depends(get_db)):
    key = _pt_key(db, authorization, token)
    if key is None:
        return _pt_401()
    r = next((r for r in _records(db, key, "potok_applicant") if r.external_id == applicant_id), None)
    if r is None:
        return JSONResponse({"errors": "Not found"}, status_code=404)
    joins = []
    for j in _pt_joins(db, key):
        p, job = j.payload, _vacancy(j.payload.get("job_id"))
        if p.get("applicant_id") != applicant_id or job is None:
            continue
        st = next((x for x in job["stages"] if x["id"] == p.get("stage_id")), job["stages"][0])
        joins.append({"id": j.external_id, "job": {"id": job["id"], "name": job["title"], "stage_name": st["name"],
                                                   "active": job["status"] == "ACTIVE"},
                      "stage": {"id": st["id"], "name": st["name"], "serial": st["position"],
                                "stage_type": _pt_type(st["stage_type"])}})
    return {"id": r.external_id, **{k: v for k, v in r.payload.items() if k != "ajs_joins"}, "ajs_joins": joins}


@router.get("/potok/api/v3/jobs/{job_id}/ajs_joins.json", summary="Демо-«Поток»: кандидаты на вакансии и их этапы")
def pt_job_joins(job_id: int, applicant_id: int | None = None, page_size: int = 20, token: str | None = None,
                 authorization: str | None = Header(None), db: Session = Depends(get_db)):
    key = _pt_key(db, authorization, token)
    if key is None:
        return _pt_401()
    job = _vacancy(job_id)
    if job is None:
        return JSONResponse({"errors": "Not found"}, status_code=404)
    out = []
    for j in _pt_joins(db, key):
        p = j.payload
        if p.get("job_id") != job_id or (applicant_id is not None and p.get("applicant_id") != applicant_id):
            continue
        st = next((x for x in job["stages"] if x["id"] == p.get("stage_id")), job["stages"][0])
        out.append({"id": j.external_id, "job_id": job_id, "applicant_id": p.get("applicant_id"),
                    "stage": {"id": st["id"], "stage_type": _pt_type(st["stage_type"])},
                    "responsible_user_id": None, "demand_id": None, "planned_employment_date": None,
                    "datetime_of_create": p.get("created_at"), "dynamic_fields": {}, "active": p.get("active", True)})
    return {"objects": out[:page_size], "has_next_page": len(out) > page_size, "page_next_cursor": None}


@router.post("/potok/api/v3/jobs/{job_id}/{applicant_id}/decline.json", summary="Демо-«Поток»: отклонить кандидата")
async def pt_decline(job_id: int, applicant_id: int, request: Request, token: str | None = None,
                     authorization: str | None = Header(None), db: Session = Depends(get_db)):
    key = _pt_key(db, authorization, token)
    if key is None:
        return _pt_401()
    d = ((await request.json()) or {}).get("decline") or {}
    if not d.get("declination_reason_id"):
        return JSONResponse({"errors": {"decline_params": ["не заполнен параметр"]}}, status_code=422)
    r = next((r for r in _pt_joins(db, key) if r.payload.get("job_id") == job_id
              and r.payload.get("applicant_id") == applicant_id), None)
    if r is None:
        return JSONResponse({"errors": {"ajs_join": ["кандидат на вакансии не найден"]}}, status_code=422)
    potok_demo_move(db, key, r.external_id, decline=True, comment=d.get("comment"))
    return {"result": "success"}


def potok_demo_pipeline(db: Session, stub_key: str) -> list[dict]:
    """Демо-«Поток» глазами рекрутёра: кандидаты на вакансиях, текущий этап и этапы воронки (для кабинета)."""
    names = {r.external_id: " ".join(x for x in (r.payload.get("last_name"), r.payload.get("first_name")) if x)
             for r in _records(db, stub_key, "potok_applicant")}
    out = []
    for j in _pt_joins(db, stub_key):
        p, job = j.payload, _vacancy(j.payload.get("job_id"))
        if job is None:
            continue
        out.append({"join_id": j.external_id, "applicant_id": p.get("applicant_id"),
                    "applicant": names.get(p.get("applicant_id")) or f"Кандидат {p.get('applicant_id')}",
                    "job_id": job["id"], "job_name": job["title"], "stage_id": p.get("stage_id"),
                    "stage_name": p.get("stage_name"), "active": p.get("active", True),
                    "stages": [{"id": x["id"], "name": x["name"], "stage_type": _pt_type(x["stage_type"])}
                               for x in job["stages"]]})
    return out


def potok_demo_move(db: Session, stub_key: str, join_id: int, *, stage_id: int | None = None,
                    decline: bool = False, comment: str | None = None) -> dict | None:
    """Демо: рекрутёр в «Потоке» переводит кандидата на этап или отклоняет (как в интерфейсе «Потока»).
    Платформа узнаёт об этом только опросом API — так же, как у настоящего «Потока». None — нет такой записи."""
    r = next((r for r in _pt_joins(db, stub_key) if r.external_id == join_id), None)
    job = _vacancy(r.payload["job_id"]) if r else None
    if r is None or job is None:
        return None
    if decline:
        r.payload = {**r.payload, "active": False, "declined_at": utcnow().isoformat()}
        db.add(AtsStubRecord(stub_key=stub_key, kind="potok_stage", external_id=r.payload["applicant_id"],
                             payload={"join_id": join_id, "job_name": job["title"], "stage_name": "Отклонён",
                                      "by": "recruiter", **({"comment": comment} if comment else {})}))
    else:
        st = next((x for x in job["stages"] if x["id"] == stage_id), None)
        if st is None:
            return None
        r.payload = {**r.payload, "stage_id": st["id"], "stage_name": st["name"], "active": True}
        db.add(AtsStubRecord(stub_key=stub_key, kind="potok_stage", external_id=r.payload["applicant_id"],
                             payload={"join_id": join_id, "job_name": job["title"], "stage_name": st["name"],
                                      "by": "recruiter"}))
    db.commit()
    return dict(r.payload)


@router.post("/potok/api/v3/ajs_joins.json", summary="Демо-«Поток»: добавить кандидата на вакансию")
async def pt_join(request: Request, token: str | None = None, authorization: str | None = Header(None),
                  db: Session = Depends(get_db)):
    key = _pt_key(db, authorization, token)
    if key is None:
        return _pt_401()
    b = (await request.json()) or {}
    job = _vacancy(b.get("job_id"))
    if job is None or not any(r.external_id == b.get("applicant_id") for r in _records(db, key, "potok_applicant")):
        return JSONResponse({"errors": {"ajs_join": ["кандидат или вакансия не найдены"]}}, status_code=422)
    if any(r.payload.get("job_id") == job["id"] and r.payload.get("applicant_id") == b["applicant_id"]
           for r in _pt_joins(db, key)):
        return JSONResponse({"ajs_join": ["кандидат на вакансии уже существует"]}, status_code=422)
    j = _pt_add_join(db, key, job, b["applicant_id"], b.get("stage_type") or "sourced")
    db.commit()
    return j


@router.post("/potok/api/v3/ajs_joins/{join_id}/change_stage.json", summary="Демо-«Поток»: перевести на этап")
async def pt_change_stage(join_id: int, request: Request, token: str | None = None,
                          authorization: str | None = Header(None), db: Session = Depends(get_db)):
    key = _pt_key(db, authorization, token)
    if key is None:
        return _pt_401()
    b = (await request.json()) or {}
    r = next((r for r in _pt_joins(db, key) if r.external_id == join_id), None)
    job = _vacancy(r.payload["job_id"]) if r else None
    stage = next((s for s in (job or {}).get("stages", []) if s["id"] == b.get("stage_id")), None)
    if r is None or stage is None:
        return JSONResponse({"errors": {"stage_id": ["этап не найден"]}}, status_code=422)
    r.payload = {**r.payload, "stage_id": stage["id"], "stage_name": stage["name"], "active": True}
    db.add(AtsStubRecord(stub_key=key, kind="potok_stage", external_id=r.payload["applicant_id"],
                         payload={"join_id": join_id, "job_name": job["title"], "stage_name": stage["name"]}))
    db.commit()
    return {"id": join_id, "stage": {"id": stage["id"], "name": stage["name"], "stage_type": _pt_type(stage["stage_type"])}}


@router.post("/potok/api/v3/events.json", summary="Демо-«Поток»: комментарий к кандидату")
async def pt_event(request: Request, token: str | None = None, authorization: str | None = Header(None),
                   db: Session = Depends(get_db)):
    key = _pt_key(db, authorization, token)
    if key is None:
        return _pt_401()
    ev = ((await request.json()) or {}).get("event") or {}
    if not ev.get("body") or not ev.get("applicant_id") or ev.get("type") != "Event::Comment":
        return JSONResponse({"errors": {"event": ["body, applicant_id и type обязательны"]}}, status_code=422)
    eid = _new_id()
    db.add(AtsStubRecord(stub_key=key, kind="potok_event", external_id=ev["applicant_id"], payload={**ev, "id": eid}))
    db.commit()
    return {"id": eid, **ev, "created_at": datetime.now(UTC).isoformat()}

