"""Этапы найма → ATS работодателя и обратно.

После шагов, меняющих этап (собеседование назначено, оффер отправлен, исход найма), платформа переводит кандидата
на этап в каждой включённой ATS компании и пишет запись в журнал передач (ats_deliveries, trigger «hiring_<этап>»):

* «Поток» — этап вакансии по типу (stage_type: interview*, offer*, accepted/hired) — ``POST /ajs_joins/{id}/
  change_stage.json``; «не прошёл» и «отказ кандидата» — ``POST /jobs/{job}/{applicant}/decline.json`` (причина
  отказа — POTOK_DECLINE_REASON_ID, у демо-«Потока» — 1; без причины — только комментарий); комментарий
  ``POST /events.json``. Если кандидат ещё не передан — сначала обычная передача (как кнопка «В ATS»).
  Сразу после перевода — опрос обратного канала (app.integrations.ats.stages.sync_company): этап из «Потока»
  возвращается в приглашение и виден обеим сторонам; push кандидату об этом этапе не дублируется.
* Talantix и Хантфлоу — этап по названию (интервью / оффер / вышел / отказ); не нашли — запись в журнале без смены.
* Вебхук — событие ``candidate.hiring_stage``: только ref кандидата, приглашение и этап (без ПДн).

Сбой ATS не отменяет шаг найма: ошибка видна в журнале передач и в карточке приглашения.
"""
from __future__ import annotations

import logging
import os
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, utcnow
from app.integrations.ats import providers
from app.integrations.ats.clients import AtsError, post_webhook
from app.integrations.ats.models import AtsDelivery, AtsLink, AtsSettings
from app.integrations.ats.providers.base import soft
from app.integrations.ats.stages import PLATFORM_STAGES, map_potok, sync_company
from app.core.enums import InvitationStatus
from app.integrations.crypto import decrypt
from app.modules.invitations.models import Invitation
from app.modules.profiles.models import CandidateProfile

log = logging.getLogger(__name__)
NAME_HINTS = {"interview": r"интервью|собесед|interview", "offer": r"оффер|offer|предложен",
              "hired": r"вышел|выход|нанят|принят на работу|hired|принят",
              "rejected": r"отказ|отклон|reject|declin|trash"}
TARGET_TITLES = {"potok": "Поток", "talantix": "Talantix", "huntflow": "Хантфлоу", "webhook": "Вебхук"}


def _delivery_ctx(db: Session, inv: Invitation, code: str) -> AtsDelivery | None:
    """Последняя успешная передача приглашения в эту ATS — в ней вакансия и связь на вакансии."""
    return db.scalar(select(AtsDelivery).where(AtsDelivery.invitation_id == inv.id, AtsDelivery.target == code,
                                               AtsDelivery.status == "ok").order_by(AtsDelivery.created_at.desc())
                     .limit(1))


def _ensure_link(db: Session, inv: Invitation, code: str, steps: list[str]) -> AtsLink:
    q = select(AtsLink).where(AtsLink.company_id == inv.company_id, AtsLink.provider == code,
                              AtsLink.candidate_user_id == inv.candidate_user_id)
    link = db.scalar(q)
    if link is None or not link.external_id or _delivery_ctx(db, inv, code) is None:
        from app.integrations.ats.service import deliver

        ds = deliver(db, inv.company_id, invitation_id=inv.id, trigger="hiring_push", only=code)
        if ds and ds[0].status != "ok":
            raise AtsError(f"Кандидат не передан: {ds[0].error}", ds[0].http_status)
        steps.append("Кандидат ещё не был передан — передан сейчас (как кнопка «В ATS»)")
        db.expire_all()
        link = db.scalar(q)
    if link is None or not link.external_id:
        raise AtsError("Кандидата нет в ATS — передача не выполнена", 422)
    return link


def _vacancy(db: Session, inv: Invitation, code: str, link: AtsLink) -> int | None:
    d = _delivery_ctx(db, inv, code)
    vid = (d.result or {}).get("vacancy_id") if d else None
    if not vid:
        conn = providers.connection(db, inv.company_id, code, create=False) if code in providers.CONNECTION_PROVIDERS \
            else None
        vid = conn.vacancy_id if conn else None
    if not vid and link.vacancies:
        vid = link.vacancies[-1].get("id")
    return int(vid) if vid else None


def _potok(db: Session, inv: Invitation, stage: str, details: str) -> dict:
    steps: list[str] = []
    link = _ensure_link(db, inv, "potok", steps)
    aid = int(link.external_id)
    vid = _vacancy(db, inv, "potok", link)
    res = {"external_id": str(aid), "applicant_id": aid, "vacancy_id": vid, "stage": stage,
           "stage_title": None, "steps": steps}
    if not vid:
        steps.append("Кандидат в базе «Потока» без вакансии — этап не меняли, только комментарий")
        soft(steps, "Комментарий", lambda: providers.make(db, inv.company_id, "potok").cl.event(aid, details))
        return res
    cl = providers.make(db, inv.company_id, "potok").cl
    entry = next((v for v in link.vacancies or [] if v.get("id") == vid), {})
    join_id = entry.get("join_id")
    if not join_id:
        state = cl.join_state(vid, aid)
        if state is None:
            join = cl.join(vid, aid)
            join_id = (join or {}).get("id")
            steps.append(f"Добавлен на вакансию {vid} (POST /ajs_joins.json)")
        else:
            join_id = state.get("id")
    res["join_id"] = join_id
    if stage == "rejected":
        conn = providers.connection(db, inv.company_id, "potok", create=False)
        demo = conn is not None and conn.mode == "demo"
        reason = int(os.getenv("POTOK_DECLINE_REASON_ID") or 0) or (1 if demo else None)
        author = int(os.getenv("POTOK_AUTHOR_ID") or 0) or (1 if demo else None)
        if reason:
            body = {"decline": {"declination_reason_id": reason, "comment": details[:500],
                                **({"author_id": author} if author else {})}}
            cl._req("POST", f"/jobs/{vid}/{aid}/decline.json", body)
            steps.append(f"Отклонён на вакансии {vid} (POST /jobs/{vid}/{aid}/decline.json)")
            res["stage_title"] = "Отклонён"
        else:
            steps.append("Отказ записан комментарием: для decline.json нужна причина отказа "
                         "(POTOK_DECLINE_REASON_ID)")
    else:
        stg = next((s for s in sorted(cl.job(vid).get("stages") or [], key=lambda s: s.get("serial") or
                                      s.get("position") or 0)
                    if map_potok(s.get("stage_type"), True) == stage), None)
        if stg is None or not join_id:
            steps.append(f"На вакансии {vid} нет этапа «{PLATFORM_STAGES[stage]}» — этап не меняли")
        else:
            cl.change_stage(int(join_id), int(stg["id"]))
            link.vacancies = [{**v, "stage_id": stg["id"]} if v.get("id") == vid else v for v in link.vacancies or []]
            db.commit()
            res.update(stage_id=stg["id"], stage_title=stg.get("name"))
            steps.append(f"Переведён на этап «{stg.get('name')}» (POST /ajs_joins/{join_id}/change_stage.json)")
    if soft(steps, "Комментарий", lambda: cl.event(aid, f"Драфт: {details}", vid) or True):
        steps.append("Комментарий с деталями этапа (POST /events.json)")
    return res


def _by_name(db: Session, inv: Invitation, code: str, stage: str, details: str) -> dict:
    """Talantix и Хантфлоу: этап по названию (типов этапов, как у «Потока», в их API нет)."""
    steps: list[str] = []
    link = _ensure_link(db, inv, code, steps)
    ext = int(link.external_id)
    vid = _vacancy(db, inv, code, link)
    res = {"external_id": str(ext), "vacancy_id": vid, "stage": stage, "stage_title": None, "steps": steps}
    if not vid:
        steps.append("Кандидат без вакансии в ATS — этап не меняли")
        return res
    p = providers.make(db, inv.company_id, code)
    hint = re.compile(NAME_HINTS[stage], re.I)
    stg = next((s for s in p.stages(vid) if hint.search(s.get("title") or "")), None)
    if stg is None:
        steps.append(f"Этап «{PLATFORM_STAGES[stage]}» не найден среди этапов вакансии {vid} — этап не меняли")
        return res
    if code == "talantix":
        p.cl.transfer([ext], int(stg["id"]))
        soft(steps, "Комментарий", lambda: p.cl.comment(ext, f"Драфт: {details}", vid))
    else:
        st = db.get(AtsSettings, inv.company_id)
        p.cl.add_to_vacancy(st.huntflow_account_id, ext, vid, int(stg["id"]), f"Драфт: {details}")
    res.update(stage_id=stg["id"], stage_title=stg.get("title"))
    steps.append(f"Переведён на этап «{stg.get('title')}»")
    return res


def _webhook(db: Session, st: AtsSettings, inv: Invitation, stage: str, hiring_stage: str, delivery_id: str) -> dict:
    from app.core.db import as_aware

    secret = decrypt(st.webhook_secret_enc)
    if not st.webhook_url or not secret:
        raise AtsError("Вебхук: не заданы адрес или секрет")
    cp = db.get(CandidateProfile, inv.candidate_user_id)
    has_consent = bool(inv.status == InvitationStatus.accepted and inv.contacts_revealed_at is not None and cp and cp.deleted_at is None)
    consent_at = as_aware(inv.contacts_revealed_at).isoformat() if (has_consent and inv.contacts_revealed_at) else None
    ev = "candidate.hiring_stage"
    payload = {"event": ev, "delivery_id": delivery_id, "candidate_ref": cp.public_ref if cp else None,
               "consent": has_consent, "consent_at": consent_at,
               "invitation_id": str(inv.id), "position_title": inv.position_title, "stage": stage,
               "stage_title": PLATFORM_STAGES[stage], "hiring_stage": hiring_stage, "at": utcnow().isoformat()}
    return {"http_status": post_webhook(st.webhook_url, secret, ev, delivery_id, payload), "stage": stage,
            "stage_title": PLATFORM_STAGES[stage], "steps": [f"Событие {ev}: этап «{PLATFORM_STAGES[stage]}»"]}


def push_stage(db: Session, inv_id: uuid.UUID, hiring_stage: str, details: str) -> list[AtsDelivery]:
    """Перевести кандидата на этап во всех включённых ATS компании; затем вернуть этап обратным каналом."""
    from app.modules.hiring.service import ATS_STAGE

    inv = db.get(Invitation, inv_id)
    stage = ATS_STAGE.get(hiring_stage)
    if inv is None or stage is None or inv.status != InvitationStatus.accepted or inv.contacts_revealed_at is None:
        return []
    st = db.get(AtsSettings, inv.company_id)
    if st is None:
        return []
    out = []
    for target in providers.enabled_targets(db, inv.company_id, st):
        d = AtsDelivery(company_id=inv.company_id, candidate_user_id=inv.candidate_user_id, invitation_id=inv.id,
                        target=target, status="pending", trigger=f"hiring_{hiring_stage}"[:32], result={},
                        attempts=1)
        db.add(d)
        db.commit()
        try:
            if target == "webhook":
                d.result = _webhook(db, st, inv, stage, hiring_stage, str(d.id))
            elif target == "potok":
                d.result = _potok(db, inv, stage, details)
            else:
                d.result = _by_name(db, inv, target, stage, details)
            d.status, d.error, d.http_status = "ok", None, d.result.get("http_status", 200)
        except AtsError as e:
            db.rollback()
            d.status, d.error, d.http_status = "error", str(e)[:500], e.status
        except Exception as e:  # noqa: BLE001 — неожиданный ответ ATS не оставляет запись «pending»
            log.exception("hiring ATS %s failed", target)
            db.rollback()
            d.status, d.error, d.http_status = "error", f"Внутренняя ошибка адаптера: {type(e).__name__}", None
        db.commit()
        out.append(d)
        if target == "potok" and d.status == "ok" and (d.result or {}).get("vacancy_id"):
            try:  # обратный канал: этап из «Потока» — в приглашение (push кандидату уже отправлен шагом найма)
                sync_company(db, inv.company_id, "potok", trigger="hiring", quiet={inv.id})
            except Exception:  # noqa: BLE001
                db.rollback()
                log.exception("hiring stage back sync failed")
    return out


def push_stage_bg(inv_id: uuid.UUID, hiring_stage: str, details: str) -> None:
    db = SessionLocal()
    try:
        push_stage(db, inv_id, hiring_stage, details)
    except Exception:  # noqa: BLE001
        log.exception("hiring ATS push failed")
    finally:
        db.close()


def ats_out(db: Session, inv: Invitation) -> list[dict]:
    """Последняя передача этапа найма в каждую ATS — для строки «Передано: Поток · этап …» у работодателя."""
    rows = db.scalars(select(AtsDelivery).where(AtsDelivery.invitation_id == inv.id,
                                                AtsDelivery.trigger.like("hiring_%"))
                      .order_by(AtsDelivery.created_at.desc())).all()
    seen, out = set(), []
    for d in rows:
        if d.target in seen:
            continue
        seen.add(d.target)
        r = d.result or {}
        out.append({"target": d.target, "target_title": TARGET_TITLES.get(d.target, d.target), "status": d.status,
                    "stage": r.get("stage"), "stage_title": r.get("stage_title") or PLATFORM_STAGES.get(
                        r.get("stage") or "", None), "error": d.error, "steps": r.get("steps") or [],
                    "trigger": d.trigger, "at": d.updated_at.isoformat()})
    return out
