"""«Смоделировать нового кандидата» — только для песочницы жюри (не для живых пользователей и не для общего демо).

Создаёт в песочнице кандидата, который проходит НАСТОЯЩИЙ тест банка (адаптивная сессия, как у демо-персон), затем
запускает обход подписок только для этого работодателя: так в кабинете и в «Уведомлениях» сразу видна цепочка
«подписался → новый кандидат прошёл тест → вошёл в топ-10 → уведомление». Письма демо-учётке не уходят (как везде),
но их текст виден в разделе «Уведомления».
"""
from __future__ import annotations

import logging
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.enums import FactSource, UserRole, WorkFormat
from app.core.errors import api_error
from app.core.ratelimit import SlidingWindow, hit
from app.modules.assessment.models import SurveyResponse, SurveyStackTag
from app.modules.auth.models import User
from app.modules.catalog.seed_data import STACK
from app.modules.jury import scope
from app.modules.matching.models import EmployerNeed
from app.modules.profiles.facts import refresh_rating, set_t0_facts
from app.modules.profiles.models import CandidateProfile, EmployerProfile
from app.modules.profiles.refs import new_public_ref
from app.modules.subs import runner, service
from app.modules.subs.models import NeedSubEntry, UserNotification
from app.core.enums import NeedStatus

log = logging.getLogger(__name__)
SIM_PREFIX = "sim-"
SIM_MAX = 8
_limit = SlidingWindow(12, 3600)
THETA = {"intern": 0.8, "junior": 1.3, "middle": 1.4, "senior": 1.9}
NAMES = ["Дарья Воронина", "Никита Орлов", "Елена Савельева", "Артём Громов", "Ксения Зайцева", "Павел Дьячков",
         "Алина Мельник", "Игорь Тарасов"]
DEFAULT_STACK = {"backend": ["python", "fastapi", "postgresql", "redis", "docker"],
                 "frontend": ["javascript", "typescript", "react", "html_css"]}


def sim_like(sid: str) -> str:
    return f"{SIM_PREFIX}%+{sid}@{scope.DOMAIN}"


def _pick_need(db: Session, employer: User, need_id) -> EmployerNeed:
    from app.modules.subs.models import NeedSubscription

    if need_id:
        n = db.get(EmployerNeed, need_id)
        if n is not None:
            return n
    sub = db.scalar(select(NeedSubscription).where(NeedSubscription.employer_user_id == employer.id,
                                                   NeedSubscription.enabled.is_(True))
                    .order_by(NeedSubscription.created_at).limit(1))
    if sub is not None:
        n = db.get(EmployerNeed, sub.need_id)
        if n is not None and n.status == NeedStatus.active:
            return n
    ep = db.get(EmployerProfile, employer.id)
    n = db.scalar(select(EmployerNeed).where(EmployerNeed.company_id == ep.company_id if ep else False,
                                             EmployerNeed.status == NeedStatus.active)
                  .order_by(EmployerNeed.created_at).limit(1)) if ep else None
    if n is None:
        raise api_error(409, "no_need", "Сначала опишите потребность, на которую можно подписаться")
    return n


def simulate(db: Session, user: User, need_id=None) -> dict:
    from app.modules.jury.seed import run_demo_test
    from app.modules.demo.seed import _user as demo_user
    from app.core.security import hash_password

    persona, sid = scope.parse(user.email)
    if persona != "employer" or not sid or not user.is_demo:
        raise api_error(403, "jury_sandbox_only", "Кнопка работает только в вашей песочнице жюри (демо-работодатель)")
    hit(_limit, sid, "subs_sim_rate", "Слишком часто, подождите немного")
    if (db.scalar(select(func.count()).select_from(User).where(User.email.like(sim_like(sid)))) or 0) >= SIM_MAX:
        raise api_error(409, "sim_limit", f"В песочнице уже {SIM_MAX} смоделированных кандидатов. "
                                          "Нажмите «Сбросить своё демо», чтобы начать заново")
    need = _pick_need(db, user, need_id)
    auto = service.get_sub(db, need.id) is None or not service.get_sub(db, need.id).enabled
    if auto:
        service.subscribe(db, need, user)
    req, _ = service.definition_of(db, need)
    direction = req.get("direction") or "backend"
    grade = req.get("grade") or "middle"
    tags = [x["tag"] for x in (req.get("stack_required") or []) + (req.get("stack_desired") or []) if x["tag"] in STACK]
    stack = list(dict.fromkeys(tags))[:8] or DEFAULT_STACK.get(direction, DEFAULT_STACK["backend"])
    with scope.use(sid):
        n = (db.scalar(select(func.count()).select_from(User).where(User.email.like(sim_like(sid)))) or 0)
        u = demo_user(db, f"{SIM_PREFIX}{secrets.token_hex(4)}+{sid}@{scope.DOMAIN}", UserRole.candidate,
                      hash_password(secrets.token_urlsafe(24)))
        u.last_login_at = utcnow()
        p = CandidateProfile(user_id=u.id, full_name=NAMES[n % len(NAMES)], phone="+7 900 000-00-02", telegram="@jury_sim",
                             city="Москва", work_format=WorkFormat.remote, relocation=False, experience_years=4.0,
                             salary_min_hidden=220_000, privacy={}, visible_to_employers=True,
                             public_ref=new_public_ref(db), onboarding_completed_at=utcnow(), roles=["developer"],
                             headline=f"{direction} · {grade} (смоделированный кандидат, демо жюри)", jury_mode=True)
        db.add(p)
        db.flush()
        sv = SurveyResponse(user_id=u.id, direction_id=direction, claimed_grade_id=grade, experience_years=4.0,
                            answers={"stack": {t: 3 for t in stack}, "roles": ["developer"], "demo": True, "jury": True})
        db.add(sv)
        db.flush()
        for t in stack:
            db.add(SurveyStackTag(survey_id=sv.id, stack_tag_id=t, self_level=3))
        set_t0_facts(db, u.id, FactSource.self_report, stack=stack, roles=["developer"],
                     soft_skills=["communication", "teamwork"], experience_years=4.0)
        db.commit()
        res: dict = {}
        for attempt in range(6):  # демо-респондент случаен: нужен подтверждённый грейд — иначе следующий seed
            res = run_demo_test(db, u.id, grade, THETA.get(grade, 1.4), 7000 + 17 * n + attempt, direction=direction)
            if res.get("confirmed"):
                break
        refresh_rating(db, u.id)
        db.commit()
    st = runner.tick(db, only_employer=user.id, force=True)
    entry = db.scalar(select(NeedSubEntry).join(service.NeedSubscription, service.NeedSubscription.id == NeedSubEntry.sub_id)
                      .where(service.NeedSubscription.need_id == need.id, NeedSubEntry.candidate_user_id == u.id))
    note = db.scalar(select(UserNotification).where(UserNotification.user_id == user.id, UserNotification.kind == "new_match")
                     .order_by(UserNotification.created_at.desc()).limit(1)) if entry and entry.in_top else None
    return {
        "candidate_ref": p.public_ref, "confirmed": bool(res.get("confirmed")), "category_id": res.get("category_id"),
        "need_id": str(need.id), "need_title": need.title, "auto_subscribed": auto,
        "entered_top": bool(entry and entry.in_top), "rank": entry.rank if entry else None,
        "score": entry.score if entry else None, "top_n": service.top_n(),
        "notification": None if note is None else {"id": str(note.id), "title": note.title, "body": note.body,
                                                   "push_state": note.push_state, "url": note.url},
        "tick": st,
    }


def purge(db: Session, sid: str, owner_ids: list) -> None:
    """Сброс песочницы: подписки, лента уведомлений и смоделированные кандидаты (в SQLite каскадов нет — явно)."""
    from sqlalchemy import delete

    from app.jury_live import service as live
    from app.modules.subs.models import NotifyPrefs, SubsDirty

    sim_ids = list(db.scalars(select(User.id).where(User.email.like(sim_like(sid)))).all())
    sub_ids = list(db.scalars(select(service.NeedSubscription.id).where(
        service.NeedSubscription.employer_user_id.in_(owner_ids))).all()) if owner_ids else []
    if sub_ids:
        db.execute(delete(NeedSubEntry).where(NeedSubEntry.sub_id.in_(sub_ids)))
        db.execute(delete(service.NeedSubscription).where(service.NeedSubscription.id.in_(sub_ids)))
    both = owner_ids + sim_ids
    if both:
        db.execute(delete(UserNotification).where(UserNotification.user_id.in_(both)))
        db.execute(delete(NotifyPrefs).where(NotifyPrefs.user_id.in_(both)))
        db.execute(delete(SubsDirty).where(SubsDirty.user_id.in_(both)))
    live.delete_guests(db, sim_ids)


FAST_FORWARD_DAYS = {5: "без ответа 3 дня и отклик без решения 5 дней", 29: "до конца срока ответа остались сутки"}


def fast_forward(db: Session, user: User, days: int) -> dict:
    """«Перемотать время» в песочнице жюри: напоминания Н6 считаются так, будто прошло days дней (5 или 29).
    Уведомления создаются с настоящим временем, приглашения и отклики не меняются."""
    from datetime import timedelta

    from sqlalchemy import update

    from app.modules.subs import delivery, reminders

    persona, sid = scope.parse(user.email)
    if persona != "employer" or not sid or not user.is_demo:
        raise api_error(403, "jury_sandbox_only", "Кнопка работает только в вашей песочнице жюри (демо-работодатель)")
    if days not in FAST_FORWARD_DAYS:
        raise api_error(422, "bad_days", "Доступно: 5 или 29 дней")
    hit(_limit, sid, "subs_sim_rate", "Слишком часто, подождите немного")
    people = set(db.scalars(select(User.id).where(User.email.in_(list(scope.emails(sid).values())))).all())
    vnow = utcnow() + timedelta(days=days, hours=1)
    out = reminders.run(db, vnow, people)
    delivery.run_digests(db, vnow, force=True, user_ids=list(people))
    delivery.dispatch(db, vnow, user_ids=list(people))
    db.execute(update(UserNotification).where(UserNotification.user_id.in_(people), UserNotification.created_at >= vnow - timedelta(seconds=1))
               .values(created_at=utcnow()))
    db.commit()
    return {"days": days, "why": FAST_FORWARD_DAYS[days], "created": out}
