"""Обратный канал ATS → платформа: этап кандидата в «Потоке» меняет этап приглашения или отклика на платформе.

Как работает. После передачи кандидата (service.deliver) в ``ats_links`` лежат id кандидата в «Потоке» и вакансии,
на которые он добавлен. Платформа опрашивает API v3 (вебхуков об этапах у «Потока» нет):
``GET /jobs/{job_id}/ajs_joins.json?applicant_id=…`` — этап (id, stage_type) и признак ``active`` (false — отказ);
названия этапов — из ``GET /jobs/{id}.json`` (один запрос на вакансию за опрос). Если метод ajs_joins компании
недоступен — ``GET /applicants/{id}.json`` (этап есть, признака отказа нет).

Тип этапа «Потока» → этап на платформе (PLATFORM_STAGES): applied / sourced / screening и свои этапы компании —
«на рассмотрении», interview_* — «собеседование», offer — «оффер», accepted — «вышел на работу», active=false —
«отказ». Что меняется на платформе:
* приглашение: статус остаётся «принято» (контакты открыты — правило ТЗ), рядом — этап у работодателя (ats_stage);
* отклик: этап (ats_stage) и статус — собеседование / оффер / выход переводят «отправлен / просмотрен» в «приглашён
  на интервью», отказ — в «отказ»; событие в истории отклика видно обеим сторонам.
Кандидат получает push при смене этапа. Каждое изменение и ошибка — в журнале ``ats_stage_events`` (без ПДн).

Когда: фоновый опрос раз в ATS_STAGE_POLL_S (по умолчанию 300 с; оба воркера uvicorn, строку подключения берёт один —
CAS по ``stages_synced_at``) и кнопка «Обновить этапы» в кабинете. Демо-«Поток» (заглушка) отвечает тем же API,
рекрутёр двигает кандидата по этапам прямо в кабинете — платформа узнаёт об этом тем же опросом.
"""
from __future__ import annotations

from datetime import timedelta
import logging
import threading
import time
import uuid

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_engine, utcnow
from app.integrations.ats import providers
from app.integrations.ats.clients import AtsError
from app.integrations.ats.models import AtsConnection, AtsDelivery, AtsLink, AtsStageEvent
from app.integrations.settings import get_isettings
from app.integrations.vacancies.models import Vacancy, VacancyApplication
from app.modules.invitations.models import Invitation

log = logging.getLogger(__name__)
PROVIDERS_WITH_STAGES = ("potok",)
PLATFORM_STAGES = {"review": "На рассмотрении", "interview": "Собеседование", "offer": "Оффер",
                   "hired": "Вышел на работу", "rejected": "Отказ"}
PROVIDER_TITLES = {"potok": "Поток"}
# Сообщение кандидату при смене этапа (на «на рассмотрении» push не шлём — это этап сразу после передачи)
PUSH = {"interview": "Вас пригласили на собеседование", "offer": "Работодатель готовит оффер",
        "hired": "Поздравляем с выходом на работу", "rejected": "Работодатель завершил рассмотрение"}


def map_potok(stage_type: str | None, active: bool | None) -> str:
    """Тип этапа «Потока» (stage_type) и признак активности на вакансии → этап на платформе."""
    if active is False:
        return "rejected"
    t = (stage_type or "").lower()
    if t in ("accepted", "hired", "employed"):
        return "hired"
    if t.startswith("offer"):
        return "offer"
    if "interview" in t:
        return "interview"
    if t in ("declined", "rejected", "refused"):
        return "rejected"
    return "review"


def _contexts(db: Session, company_id: uuid.UUID, code: str) -> dict[tuple[uuid.UUID, int], AtsDelivery]:
    """(кандидат, вакансия в ATS) → последняя успешная передача: к ней привязаны приглашение или отклик."""
    rows = db.scalars(select(AtsDelivery).where(AtsDelivery.company_id == company_id, AtsDelivery.target == code,
                                                AtsDelivery.status == "ok")
                      .order_by(AtsDelivery.created_at.desc())).all()
    out: dict[tuple[uuid.UUID, int], AtsDelivery] = {}
    for d in rows:
        vid = (d.result or {}).get("vacancy_id")
        if vid and (d.invitation_id or d.application_id):
            out.setdefault((d.candidate_user_id, int(vid)), d)
    return out


def _apply(db: Session, ev: AtsStageEvent, target, stage: str, info: dict) -> str:
    """Записать этап в приглашение или отклик; вернуть описание изменения для журнала."""
    target.ats_stage = info
    title = PLATFORM_STAGES[stage]
    if isinstance(target, Invitation):
        return f"Приглашение «{target.position_title}»: этап «{title}» (статус «принято» сохранён)"
    a: VacancyApplication = target
    from app.integrations.vacancies.router import STATUS_TITLES

    now = utcnow().isoformat()
    events = [*(a.events or []), {"at": now, "status": "ats_stage", "title": f"Этап у работодателя: {title}",
                                  "by": "ats", "note": f"«{PROVIDER_TITLES.get(ev.provider, ev.provider)}»: "
                                                       f"{info.get('stage_name') or title}"}]
    effect = f"Отклик: этап «{title}»"
    new = None
    if stage in ("interview", "offer", "hired") and a.status in ("sent", "viewed"):
        new = "accepted"
    elif stage == "rejected" and a.status in ("sent", "viewed", "accepted"):
        new = "rejected"
    if new:
        a.status, a.responded_at = new, a.responded_at or utcnow()
        a.viewed_at = a.viewed_at or utcnow()
        events.append({"at": now, "status": new, "title": STATUS_TITLES[new], "by": "ats",
                       "note": f"по этапу в ATS: {info.get('stage_name') or title}"})
        effect += f", статус «{STATUS_TITLES[new]}»"
    a.events = events
    return effect


def _notify(db: Session, target, stage: str) -> None:
    if stage not in PUSH:
        return
    try:
        from app.integrations.push.service import send_to_user

        if isinstance(target, Invitation):
            send_to_user(db, target.candidate_user_id, PUSH[stage], f"«{target.position_title}»",
                         "/candidate/invitations", f"inv-stage-{target.id}")
        else:
            v = db.get(Vacancy, target.vacancy_id)
            send_to_user(db, target.candidate_user_id, PUSH[stage], f"«{v.title if v else 'Вакансия'}»",
                         "/candidate/vacancies", f"app-stage-{target.id}")
    except Exception:  # noqa: BLE001 — push не должен ломать опрос
        db.rollback()
        log.exception("ATS stage push failed")


def _error(db: Session, company_id: uuid.UUID, code: str, message: str, **kw) -> None:
    """Ошибка опроса в журнал — без повтора одной и той же ошибки при каждом опросе."""
    last = db.scalar(select(AtsStageEvent).where(AtsStageEvent.company_id == company_id, AtsStageEvent.provider == code)
                     .order_by(AtsStageEvent.created_at.desc()).limit(1))
    if last is not None and last.status == "error" and last.error == message[:500] \
            and last.external_id == kw.get("external_id"):
        return
    db.add(AtsStageEvent(company_id=company_id, provider=code, status="error", error=message[:500], **kw))


def sync_company(db: Session, company_id: uuid.UUID, code: str = "potok", *, trigger: str = "poll",
                 quiet: set | frozenset = frozenset()) -> dict:
    """Опросить этапы всех переданных кандидатов компании в ATS и перенести изменения на платформу.
    quiet — id приглашений, кандидатам которых push об этапе не нужен (этап поставил шаг найма, push уже ушёл)."""
    if code not in PROVIDERS_WITH_STAGES:
        raise AtsError("Этапы из этой ATS не читаются", 404)
    conn = db.get(AtsConnection, (company_id, code))
    if conn is None or not conn.enabled:
        raise AtsError(f"«{PROVIDER_TITLES[code]}» не подключён", 422)
    started = time.monotonic()
    info = {"at": utcnow().isoformat(), "trigger": trigger, "checked": 0, "changed": 0, "errors": 0,
            "mode": conn.mode, "error": None}
    try:
        cl = providers.make(db, company_id, code).cl
    except AtsError as e:
        info.update(errors=1, error=str(e))
        _error(db, company_id, code, str(e))
        conn.stages_synced_at, conn.stages_sync_info = utcnow(), info
        db.commit()
        return info
    links = db.scalars(select(AtsLink).where(AtsLink.company_id == company_id, AtsLink.provider == code,
                                             AtsLink.external_id.is_not(None))).all()
    ctx = _contexts(db, company_id, code)
    jobs: dict[int, dict[int, dict]] = {}
    batch = get_isettings().ats_stage_poll_batch
    for link in links:
        for v in list(link.vacancies or []):
            job_id = v.get("id")
            if not job_id or info["checked"] >= batch:
                continue
            aid = int(link.external_id)
            base = dict(candidate_user_id=link.candidate_user_id, external_id=link.external_id, job_id=job_id)
            d = ctx.get((link.candidate_user_id, int(job_id)))
            if d is not None:
                base.update(invitation_id=d.invitation_id, application_id=d.application_id)
            try:
                state = cl.join_state(int(job_id), aid)
                if state is not None and job_id not in jobs:
                    jobs[job_id] = {s["id"]: s for s in (cl.job(int(job_id)).get("stages") or []) if "id" in s}
            except AtsError as e:
                info["errors"] += 1
                info["error"] = str(e)
                _error(db, company_id, code, str(e), **base)
                if e.status in (401, 402, 429) or e.status is None:  # токен, подписка, лимит, сеть — дальше не идём
                    db.commit()
                    return _finish(db, conn, info, started)
                continue
            info["checked"] += 1
            if state is None:
                continue
            st = jobs.get(job_id, {}).get(state.get("stage_id")) or {}
            stage_type = state.get("stage_type") or st.get("stage_type")
            stage_name = st.get("name") or state.get("stage_name")
            stage = map_potok(stage_type, state.get("active"))
            target = (db.get(Invitation, d.invitation_id) if d is not None and d.invitation_id else
                      db.get(VacancyApplication, d.application_id) if d is not None and d.application_id else None)
            prev = (target.ats_stage or {}) if target is not None else (v.get("ats") or {})
            if prev.get("stage_id") == state.get("stage_id") and prev.get("active") == state.get("active") \
                    and prev.get("stage") == stage:
                continue
            rec = {"provider": code, "stage": stage, "title": PLATFORM_STAGES[stage], "stage_name": stage_name,
                   "stage_type": stage_type, "stage_id": state.get("stage_id"), "active": state.get("active"),
                   "job_id": job_id, "at": utcnow().isoformat()}
            ev = AtsStageEvent(company_id=company_id, provider=code, **base, join_id=state.get("id"), stage_id=state.get("stage_id"), stage_name=stage_name,
                               stage_type=stage_type, active=state.get("active"), stage=stage,
                               prev_stage=prev.get("stage"), status="ok")
            ev.effect = _apply(db, ev, target, stage, rec) if target is not None else \
                "Передача без приглашения и отклика — этап только в журнале"
            # этап в связи: без приглашения/отклика сравниваем с ним; stage_id — текущий для повторной передачи
            link.vacancies = [{**x, "stage_id": state.get("stage_id"), "ats": rec} if x.get("id") == job_id else x
                              for x in (link.vacancies or [])]
            db.add(ev)
            db.commit()
            info["changed"] += 1
            if target is not None and prev.get("stage") != stage and getattr(target, "id", None) not in quiet:
                _notify(db, target, stage)
    return _finish(db, conn, info, started)


def _finish(db: Session, conn: AtsConnection, info: dict, started: float) -> dict:
    info["ms"] = int((time.monotonic() - started) * 1000)
    conn.stages_synced_at, conn.stages_sync_info = utcnow(), info
    db.commit()
    return info


def claim(db: Session, company_id: uuid.UUID, code: str, interval_s: float) -> bool:
    """Взять подключение на опрос (один воркер из двух): CAS по stages_synced_at."""
    now = utcnow()
    r = db.execute(update(AtsConnection)
                   .where(AtsConnection.company_id == company_id, AtsConnection.provider == code,
                          or_(AtsConnection.stages_synced_at.is_(None),
                              AtsConnection.stages_synced_at < now - timedelta(seconds=interval_s)))
                   .values(stages_synced_at=now).execution_options(synchronize_session=False))
    db.commit()
    return r.rowcount == 1


def sync_due() -> int:
    """Фоновый опрос: подключения, у которых есть переданные кандидаты и подошло время. Возвращает число опрошенных."""
    interval = get_isettings().ats_stage_poll_s
    get_engine()
    done = 0
    with SessionLocal() as db:
        cids = db.scalars(select(AtsConnection.company_id).where(
            AtsConnection.provider.in_(PROVIDERS_WITH_STAGES), AtsConnection.enabled.is_(True),
            or_(AtsConnection.stages_synced_at.is_(None),
                AtsConnection.stages_synced_at < utcnow() - timedelta(seconds=interval)),
            select(AtsLink.id).where(AtsLink.company_id == AtsConnection.company_id,
                                     AtsLink.provider == AtsConnection.provider,
                                     AtsLink.external_id.is_not(None)).exists())).all()
        db.commit()
        for cid in cids:
            for code in PROVIDERS_WITH_STAGES:
                if not claim(db, cid, code, interval):
                    continue
                try:
                    sync_company(db, cid, code, trigger="poll")
                    done += 1
                except AtsError:
                    db.rollback()
                except Exception:  # noqa: BLE001 — одна компания не должна останавливать опрос остальных
                    db.rollback()
                    log.exception("ATS stage sync failed for %s", cid)
    return done


_started = False
_mx = threading.Lock()


def start_poller() -> bool:
    """Запустить фоновый опрос (по потоку на воркер; одну компанию опрашивает один воркер — см. claim)."""
    global _started
    interval = get_isettings().ats_stage_poll_s
    with _mx:
        if _started or interval <= 0:
            return False
        _started = True

    def loop() -> None:
        time.sleep(min(60.0, interval))
        while True:
            try:
                sync_due()
            except Exception:  # noqa: BLE001
                log.exception("ATS stage poller")
            time.sleep(min(60.0, max(10.0, interval / 5)))

    threading.Thread(target=loop, name="ats-stage-poller", daemon=True).start()
    return True


def stage_out(rec: dict | None, side: str) -> dict | None:
    """Этап у работодателя для карточки приглашения или отклика. Кандидату — без внутреннего названия этапа ATS."""
    if not rec or rec.get("stage") not in PLATFORM_STAGES:
        return None
    out = {"stage": rec["stage"], "title": PLATFORM_STAGES[rec["stage"]], "at": rec.get("at"),
           "provider": rec.get("provider"), "provider_title": PROVIDER_TITLES.get(rec.get("provider"), "ATS")}
    if side == "employer":
        out.update(stage_name=rec.get("stage_name"), stage_type=rec.get("stage_type"))
    return out


def event_out(e: AtsStageEvent, refs: dict) -> dict:
    return {"id": str(e.id), "provider": e.provider, "provider_title": PROVIDER_TITLES.get(e.provider, e.provider),
            "candidate_ref": refs.get(e.candidate_user_id), "invitation_id": str(e.invitation_id) if e.invitation_id
            else None, "application_id": str(e.application_id) if e.application_id else None,
            "external_id": e.external_id, "job_id": e.job_id, "join_id": e.join_id, "stage_id": e.stage_id,
            "stage_name": e.stage_name, "stage_type": e.stage_type, "active": e.active, "stage": e.stage,
            "stage_title": PLATFORM_STAGES.get(e.stage or "", None), "prev_stage": e.prev_stage,
            "prev_stage_title": PLATFORM_STAGES.get(e.prev_stage or "", None), "effect": e.effect,
            "status": e.status, "error": e.error, "created_at": e.created_at.isoformat()}
